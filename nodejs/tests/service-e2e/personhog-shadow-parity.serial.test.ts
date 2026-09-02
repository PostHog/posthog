// Serial e2e: drives the Postgres and personhog person backends against real
// infrastructure and compares them through the routing store's own shadow
// machinery. The personhog half is the real stack (identity, leader-mode
// router, leader), not a model, so this catches contract drift a Jest mock
// cannot: proto encoding, uuid derivation, the saga's verdict vocabulary,
// and the identity repointing a merge leaves behind.
//
// Requires the personhog services on top of the usual serial-test infra:
// `docker compose -f docker-compose.dev.yml --profile ingestion up`, or a
// `hogli start` dev stack (the `personhog` capability). Addresses override
// via PERSONHOG_E2E_ROUTER_ADDR / PERSONHOG_E2E_IDENTITY_ADDR.
import { DateTime } from 'luxon'
import { isDeepStrictEqual } from 'node:util'
import { Pool } from 'pg'

import {
    KAFKA_INGESTION_WARNINGS,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
    KAFKA_PERSON_MERGE_EVENTS,
} from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import {
    INGESTION_WARNINGS_OUTPUT,
    PERSONS_OUTPUT,
    PERSON_DISTINCT_IDS_OUTPUT,
    PERSON_MERGE_EVENTS_OUTPUT,
} from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { PersonHogClient } from '~/common/personhog/client'
import { createIdentityClients } from '~/common/personhog/identity-clients'
import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import {
    personhogStoreShadowComparedCounter,
    personhogStoreShadowDivergenceCounter,
    personhogStoreShadowErrorsCounter,
} from '~/common/persons/metrics'
import { PostgresPersonRepository } from '~/common/persons/repositories/postgres-person-repository'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import { BatchWritingPersonsStore } from '~/ingestion/common/persons/batch-writing-person-store'
import { PersonOutputs } from '~/ingestion/common/persons/person-context'
import { createDefaultSyncMergeMode } from '~/ingestion/common/persons/person-merge-types'
import { extractEventOps } from '~/ingestion/common/persons/person-update'
import { uuidFromDistinctId } from '~/ingestion/common/persons/person-uuid'
import { PersonhogPersonsStore } from '~/ingestion/common/persons/personhog-persons-store'
import { MergePersonsRequest } from '~/ingestion/common/persons/persons-store'
import { RoutingPersonsStore } from '~/ingestion/common/persons/routing-persons-store'
import { Hub } from '~/types'

import { createOrganization, createTeam } from '../helpers/sql'

jest.setTimeout(60000)

const ROUTER_ADDR = process.env.PERSONHOG_E2E_ROUTER_ADDR ?? '127.0.0.1:50054'
const IDENTITY_ADDR = process.env.PERSONHOG_E2E_IDENTITY_ADDR ?? '127.0.0.1:50055'
// Where the personhog services keep their validation tables; the writer
// applies the leader's changelog here.
const PERSONS_DATABASE_URL =
    process.env.PERSONHOG_E2E_PERSONS_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/posthog_persons'

const counterTotal = async (counter: { get: () => Promise<{ values: { value: number }[] }> }): Promise<number> =>
    (await counter.get()).values.reduce((sum, entry) => sum + entry.value, 0)

describe('personhog shadow parity (e2e)', () => {
    let hub: Hub
    let kafkaProducer: KafkaProducerWrapper
    let routerClient: PersonHogClient
    let closeIdentity: () => void
    let personhogStore: PersonhogPersonsStore
    let pgStore: BatchWritingPersonsStore
    let routing: RoutingPersonsStore
    let personsDb: Pool = undefined as unknown as Pool
    let organizationId: string
    let teamId: number
    let batchId = 0

    // Distinct ids are unique per run: the personhog side writes shared
    // dev tables, so a fixed id would meet a person a previous run made.
    const runTag = new UUIDT().toString().slice(0, 13)
    const id = (name: string) => `e2e-${runTag}-${name}`

    const outputs = (): PersonOutputs =>
        new IngestionOutputs({
            [PERSONS_OUTPUT]: new SingleIngestionOutput(PERSONS_OUTPUT, KAFKA_PERSON, kafkaProducer, 'test'),
            [PERSON_DISTINCT_IDS_OUTPUT]: new SingleIngestionOutput(
                PERSON_DISTINCT_IDS_OUTPUT,
                KAFKA_PERSON_DISTINCT_ID,
                kafkaProducer,
                'test'
            ),
            [INGESTION_WARNINGS_OUTPUT]: new SingleIngestionOutput(
                INGESTION_WARNINGS_OUTPUT,
                KAFKA_INGESTION_WARNINGS,
                kafkaProducer,
                'test'
            ),
            [PERSON_MERGE_EVENTS_OUTPUT]: new SingleIngestionOutput(
                PERSON_MERGE_EVENTS_OUTPUT,
                KAFKA_PERSON_MERGE_EVENTS,
                kafkaProducer,
                'test'
            ),
        })

    const ops = (properties: Record<string, unknown>, event = '$set') =>
        extractEventOps({
            event,
            distinct_id: 'e2e',
            properties,
            team_id: teamId,
            uuid: new UUIDT().toString(),
            ip: null,
            now: new Date().toISOString(),
            site_url: '',
        } as any)

    const createThroughBoth = async (distinctId: string, properties: Record<string, unknown>, batch: number) => {
        const result = await routing.createPerson(
            DateTime.utc(),
            properties,
            {},
            {},
            teamId,
            null,
            false,
            uuidFromDistinctId(teamId, distinctId),
            { distinctId },
            undefined,
            undefined,
            batch
        )
        if (!result.success) {
            throw new Error('creation failed')
        }
        return result.person
    }

    const divergences = () => counterTotal(personhogStoreShadowDivergenceCounter)
    const shadowErrors = () => counterTotal(personhogStoreShadowErrorsCounter)

    interface DurableRow {
        uuid: string
        properties: Record<string, unknown>
        is_identified: boolean
    }

    const mainRowByDistinctId = async (distinctId: string): Promise<DurableRow | null> => {
        const { rows } = await hub.postgres.query<DurableRow>(
            PostgresUse.PERSONS_WRITE,
            `SELECT p.uuid, p.properties, p.is_identified
               FROM posthog_persondistinctid d
               JOIN posthog_person p ON p.id = d.person_id
              WHERE d.team_id = $1 AND d.distinct_id = $2`,
            [teamId, distinctId],
            'personhog-shadow-parity-main-row'
        )
        return rows[0] ?? null
    }

    const tmpRowByDistinctId = async (distinctId: string): Promise<DurableRow | null> => {
        const { rows } = await personsDb.query<DurableRow>(
            `SELECT p.uuid, p.properties, p.is_identified
               FROM personhog_persondistinctid_tmp d
               JOIN personhog_person_tmp p ON p.id = d.person_id AND p.team_id = d.team_id
              WHERE d.team_id = $1 AND d.distinct_id = $2
                AND d.is_deleted = false AND p.is_deleted = false`,
            [teamId, distinctId]
        )
        return rows[0] ?? null
    }

    /**
     * Asserts the durable rows behind one distinct id agree between the
     * main tables (the Postgres backend's writes) and the personhog
     * validation tables (identity's mappings plus the writer applying the
     * leader's changelog). The writer is asynchronous, so this polls until
     * the validation row converges or the deadline passes; the final
     * expectations then print whatever it last held.
     */
    const expectDurableRowParity = async (distinctId: string): Promise<void> => {
        const main = await mainRowByDistinctId(distinctId)
        expect(main).not.toBeNull()
        const deadline = Date.now() + 20_000
        let tmp: DurableRow | null = null
        for (;;) {
            tmp = await tmpRowByDistinctId(distinctId)
            if (
                tmp !== null &&
                tmp.uuid === main!.uuid &&
                tmp.is_identified === main!.is_identified &&
                isDeepStrictEqual(tmp.properties, main!.properties)
            ) {
                break
            }
            if (Date.now() > deadline) {
                break
            }
            await new Promise((resolve) => setTimeout(resolve, 250))
        }
        expect(tmp).not.toBeNull()
        expect(tmp!.uuid).toBe(main!.uuid)
        expect(tmp!.is_identified).toBe(main!.is_identified)
        expect(tmp!.properties).toEqual(main!.properties)
    }

    beforeAll(async () => {
        hub = await createHub({})
        kafkaProducer = await KafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        routerClient = PersonHogClient.fromConfig({
            addr: ROUTER_ADDR,
            clientName: 'personhog-shadow-parity-e2e',
            timeoutMs: 10_000,
        })
        const identityClients = createIdentityClients(
            { addr: IDENTITY_ADDR, clientName: 'personhog-shadow-parity-e2e', timeoutMs: 10_000 },
            { mergeTimeoutMs: 35_000 }
        )
        closeIdentity = identityClients.close
        const writeRepository = new PersonHogPersonWriteRepository(
            routerClient,
            identityClients.identity,
            'personhog-shadow-parity-e2e'
        )
        try {
            await writeRepository.resolvePersonsByDistinctIds([{ teamId: 1, distinctId: id('ping') }], 'e2e-ping')
        } catch (error) {
            throw new Error(
                `personhog stack not reachable (router ${ROUTER_ADDR}, identity ${IDENTITY_ADDR}); ` +
                    `start it with \`docker compose -f docker-compose.dev.yml --profile ingestion up\` ` +
                    `or a hogli dev stack. Cause: ${error instanceof Error ? error.message : String(error)}`
            )
        }
        personhogStore = new PersonhogPersonsStore(writeRepository, {
            maxConcurrentUpdates: 10,
            updateAllProperties: false,
            syncMergeMoveLimit: 10_000,
        })
        pgStore = new BatchWritingPersonsStore(new PostgresPersonRepository(hub.postgres), outputs(), {
            metricEmissionIntervalMs: 0,
        })
        routing = new RoutingPersonsStore(pgStore, personhogStore, 'shadow')
        personsDb = new Pool({ connectionString: PERSONS_DATABASE_URL, max: 2 })
        organizationId = await createOrganization(hub.postgres)
        teamId = await createTeam(hub.postgres, organizationId)
    })

    afterAll(async () => {
        routerClient?.close()
        closeIdentity?.()
        await personsDb?.end()
        await kafkaProducer?.disconnect()
        if (hub) {
            await closeHub(hub)
        }
    })

    beforeEach(() => {
        batchId += 1
        personhogStoreShadowDivergenceCounter.reset()
        personhogStoreShadowComparedCounter.reset()
        personhogStoreShadowErrorsCounter.reset()
    })

    afterEach(() => {
        routing.releaseBatch(batchId)
    })

    it('creation and updates read back identically through both backends', async () => {
        const distinctId = id('reader')
        await createThroughBoth(distinctId, { plan: 'free' }, batchId)
        const person = await routing.fetchForUpdate(teamId, distinctId, batchId)
        expect(person).not.toBeNull()
        await routing.applyEventOps(person!, ops({ $set: { plan: 'pro', level: 3 } }), distinctId, batchId)
        await routing.flush()
        routing.releaseBatch(batchId)

        // A fresh batch, so both sides read their backend rather than a
        // cached answer; the shadow comparison is the assertion surface.
        batchId += 1
        const reread = await routing.fetchForUpdate(teamId, distinctId, batchId)

        expect(reread?.uuid).toBe(uuidFromDistinctId(teamId, distinctId))
        expect(reread?.properties).toMatchObject({ plan: 'pro', level: 3 })
        expect(await counterTotal(personhogStoreShadowComparedCounter)).toBeGreaterThan(0)
        expect(await divergences()).toBe(0)
        expect(await shadowErrors()).toBe(0)
        await expectDurableRowParity(distinctId)
    })

    it('a single-source merge settles the same survivor and verdict on both backends', async () => {
        const target = id('merge-target')
        const source = id('merge-source')
        await createThroughBoth(target, { origin: 'target' }, batchId)
        await createThroughBoth(source, { origin: 'source' }, batchId)

        const request: MergePersonsRequest = {
            teamId,
            targetDistinctId: target,
            sources: [{ distinctId: source, eventUuid: new UUIDT().toString() }],
            eventOps: ops({ $set: { merged: 'yes' } }, '$identify'),
            eventUuid: new UUIDT().toString(),
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: Date.now(),
        }
        const result = await routing.mergePersons(request, batchId)
        await result.kafkaAck

        expect(result.survivor?.uuid).toBe(uuidFromDistinctId(teamId, target))
        expect(result.results[0]?.outcome).toBe('merged')
        // compareMerge checked the shadow's survivor uuid and per-source
        // verdict against these; a saga whose vocabulary or op-id handling
        // drifted from the client mapping lands here as a divergence.
        expect(await counterTotal(personhogStoreShadowComparedCounter)).toBeGreaterThan(0)
        expect(await divergences()).toBe(0)
        expect(await shadowErrors()).toBe(0)
    })

    it('updates and a merge interleaved in one batch settle identically', async () => {
        const target = id('weave-target')
        const source = id('weave-source')
        await createThroughBoth(target, { shared: 'target', origin: 'target' }, batchId)
        await createThroughBoth(source, { shared: 'source', extra: 'source' }, batchId)

        // A buffered update on the source before the merge: Postgres folds
        // it through its cache, personhog drains the lane to the leader
        // before the saga runs; either way it must reach the survivor with
        // source precedence, so `shared` still settles to the target's value.
        const sourcePerson = await routing.fetchForUpdate(teamId, source, batchId)
        await routing.applyEventOps(sourcePerson!, ops({ $set: { updated: 'pre-merge' } }), source, batchId)

        const mergeOps = ops({ $set: { mergedBy: 'event' } }, '$identify')
        const merged = await routing.mergePersons(
            {
                teamId,
                targetDistinctId: target,
                sources: [{ distinctId: source, eventUuid: new UUIDT().toString() }],
                eventOps: mergeOps,
                eventUuid: new UUIDT().toString(),
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: Date.now(),
            },
            batchId
        )
        await merged.kafkaAck
        expect(merged.results[0]?.outcome).toBe('merged')
        // The follow-up property update the processor runs after a merge:
        // Postgres leaves the event ops to it, the saga already applied
        // them, and the idempotent re-fold converges the two.
        if (merged.survivorNeedsUpdate ?? true) {
            await routing.applyEventOps(merged.survivor!, mergeOps, target, batchId)
        }

        // A post-merge update addressed by the merged-away id, still in the
        // same batch: both backends must land it on the survivor.
        const viaOldId = await routing.fetchForUpdate(teamId, source, batchId)
        expect(viaOldId?.uuid).toBe(uuidFromDistinctId(teamId, target))
        await routing.applyEventOps(viaOldId!, ops({ $set: { postMerge: 'yes' } }), source, batchId)

        await routing.flush()
        routing.releaseBatch(batchId)

        batchId += 1
        const finalState = await routing.fetchForUpdate(teamId, target, batchId)
        expect(finalState?.properties).toMatchObject({
            shared: 'target',
            origin: 'target',
            extra: 'source',
            updated: 'pre-merge',
            mergedBy: 'event',
            postMerge: 'yes',
        })
        expect(await divergences()).toBe(0)
        expect(await shadowErrors()).toBe(0)
        // The durable rows behind both ids: the main tables against the
        // validation tables the identity service and the writer maintain.
        await expectDurableRowParity(target)
        await expectDurableRowParity(source)
    })

    it('a merged-away id reads the survivor on both backends', async () => {
        const target = id('heal-target')
        const source = id('heal-source')
        await createThroughBoth(target, {}, batchId)
        await createThroughBoth(source, {}, batchId)
        const merged = await routing.mergePersons(
            {
                teamId,
                targetDistinctId: target,
                sources: [{ distinctId: source, eventUuid: new UUIDT().toString() }],
                eventOps: ops({}, '$identify'),
                eventUuid: new UUIDT().toString(),
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: Date.now(),
            },
            batchId
        )
        await merged.kafkaAck
        routing.releaseBatch(batchId)

        // The purge dropped the personhog side's cache for both ids, so this
        // read re-resolves through the real identity service, whose mappings
        // the saga repointed; Postgres reads its own moved rows.
        batchId += 1
        const viaSource = await routing.fetchForUpdate(teamId, source, batchId)

        expect(viaSource?.uuid).toBe(uuidFromDistinctId(teamId, target))
        expect(await divergences()).toBe(0)
        expect(await shadowErrors()).toBe(0)
    })
})
