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
import { MergeMode, createDefaultSyncMergeMode } from '~/ingestion/common/persons/person-merge-types'
import { extractEventOps } from '~/ingestion/common/persons/person-update'
import { uuidFromDistinctId } from '~/ingestion/common/persons/person-uuid'
import { PersonhogPersonsStore } from '~/ingestion/common/persons/personhog-persons-store'
import { MergePersonsRequest, MergePersonsResult } from '~/ingestion/common/persons/persons-store'
import { RoutingPersonsStore } from '~/ingestion/common/persons/routing-persons-store'
import { Hub } from '~/types'

import { createOrganization, createTeam } from '../helpers/sql'

jest.setTimeout(60000)

const ROUTER_ADDR = process.env.PERSONHOG_E2E_ROUTER_ADDR ?? '127.0.0.1:50054'
const IDENTITY_ADDR = process.env.PERSONHOG_E2E_IDENTITY_ADDR ?? '127.0.0.1:50055'
// Where the personhog services keep their validation tables; the writer
// applies the leader's changelog here. The compose services default to
// the `posthog` database, so a compose-launched stack needs
// POSTHOG_PERSONS_DB_NAME=posthog_persons exported (hogli sets it).
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

    const createThroughBoth = async (
        distinctId: string,
        properties: Record<string, unknown>,
        batch: number,
        extraDistinctIds?: string[],
        isIdentified = false
    ) => {
        const result = await routing.createPerson(
            DateTime.utc(),
            properties,
            {},
            {},
            teamId,
            null,
            isIdentified,
            uuidFromDistinctId(teamId, distinctId),
            { distinctId },
            extraDistinctIds?.map((extra) => ({ distinctId: extra })),
            undefined,
            batch
        )
        if (!result.success) {
            throw new Error('creation failed')
        }
        return result.person
    }

    /** One merge through both backends, with the ack awaited. */
    const runMerge = async (
        targetDistinctId: string,
        sourceDistinctIds: string[],
        opts: {
            allowIdentifiedSources?: boolean
            mergeMode?: MergeMode
            eventUuid?: string
            sourceEventUuids?: string[]
            set?: Record<string, unknown>
        } = {}
    ) => {
        const mergeOps = ops({ $set: opts.set ?? {} }, '$identify')
        // The processor marks the caller identified on every merge-shaped
        // event and applies it on the follow-up update; the saga stamps the
        // survivor itself, so without this the Postgres row lags behind.
        mergeOps.isIdentified = true
        const result = await routing.mergePersons(
            {
                teamId,
                targetDistinctId,
                sources: sourceDistinctIds.map((distinctId, i) => ({
                    distinctId,
                    eventUuid: opts.sourceEventUuids?.[i] ?? new UUIDT().toString(),
                })),
                eventOps: mergeOps,
                eventUuid: opts.eventUuid ?? new UUIDT().toString(),
                allowIdentifiedSources: opts.allowIdentifiedSources ?? false,
                mergeMode: opts.mergeMode ?? createDefaultSyncMergeMode(),
                createdAtMs: Date.now(),
            },
            batchId
        )
        await result.kafkaAck
        return { result, mergeOps }
    }

    /**
     * The follow-up property update the processor runs after a merge:
     * Postgres leaves the event ops to it, the saga already applied them,
     * and the idempotent re-fold converges the two.
     */
    const applyMergeFollowUp = async (
        result: MergePersonsResult,
        mergeOps: ReturnType<typeof ops>,
        targetDistinctId: string
    ) => {
        if ((result.survivorNeedsUpdate ?? true) && result.survivor) {
            await routing.applyEventOps(result.survivor, mergeOps, targetDistinctId, batchId)
        }
    }

    const divergences = () => counterTotal(personhogStoreShadowDivergenceCounter)
    const shadowErrors = () => counterTotal(personhogStoreShadowErrorsCounter)
    const divergencesByField = async (field: string): Promise<number> =>
        (await personhogStoreShadowDivergenceCounter.get()).values
            .filter((entry) => entry.labels.field === field)
            .reduce((sum, entry) => sum + entry.value, 0)

    interface DurableRow {
        uuid: string
        properties: Record<string, unknown>
        is_identified: boolean
        created_at: string
    }

    const mainRowByDistinctId = async (distinctId: string): Promise<DurableRow | null> => {
        const { rows } = await hub.postgres.query<DurableRow>(
            PostgresUse.PERSONS_WRITE,
            `SELECT p.uuid, p.properties, p.is_identified,
                    (extract(epoch from p.created_at) * 1000)::bigint::text AS created_at
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
            `SELECT p.uuid, p.properties, p.is_identified,
                    (extract(epoch from p.created_at) * 1000)::bigint::text AS created_at
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
                tmp.created_at === main!.created_at &&
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
        expect(tmp!.created_at).toBe(main!.created_at)
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
        const [afterSet] = await routing.applyEventOps(
            person!,
            ops({ $set: { plan: 'pro', level: 3 } }),
            distinctId,
            batchId
        )
        // $set_once must not beat the standing value and $unset must land:
        // Postgres refines these client-side, the leader server-side, and
        // this is where the two refinements could drift. Chained on the
        // returned person, as the processor chains events: Postgres refines
        // against the caller's snapshot, so a stale one hides the unset.
        await routing.applyEventOps(
            afterSet,
            ops({ $set_once: { plan: 'ignored', fresh: 'kept' }, $unset: ['level'] }),
            distinctId,
            batchId
        )
        await routing.flush()
        routing.releaseBatch(batchId)

        // The durable rows first: waiting for the writer here also makes the
        // checking read below deterministic, since the identity resolve
        // serves writer-applied state.
        await expectDurableRowParity(distinctId)

        // A fresh batch, so both sides read their backend rather than a
        // cached answer; the shadow comparison is the assertion surface.
        // The checking read exercises the other personhog read path, the
        // identity resolve without a leader hop.
        batchId += 1
        const checked = await routing.fetchForChecking(teamId, distinctId, batchId)
        expect(checked?.uuid).toBe(uuidFromDistinctId(teamId, distinctId))
        const reread = await routing.fetchForUpdate(teamId, distinctId, batchId)

        expect(reread?.uuid).toBe(uuidFromDistinctId(teamId, distinctId))
        expect(reread?.properties).toEqual({ plan: 'pro', fresh: 'kept' })
        expect(await counterTotal(personhogStoreShadowComparedCounter)).toBeGreaterThan(0)
        expect(await divergences()).toBe(0)
        expect(await shadowErrors()).toBe(0)
    })

    it('a merge of two unseen ids births the person with both, identically', async () => {
        const target = id('birth-target')
        const source = id('birth-source')
        const { result, mergeOps } = await runMerge(target, [source], { set: { born: 'yes' } })

        expect(result.results[0]?.outcome).toBe('attached')
        expect(result.survivor?.uuid).toBe(uuidFromDistinctId(teamId, target))
        await applyMergeFollowUp(result, mergeOps, target)
        await routing.flush()
        routing.releaseBatch(batchId)
        await expectDurableRowParity(target)
        await expectDurableRowParity(source)

        batchId += 1
        const viaSource = await routing.fetchForUpdate(teamId, source, batchId)
        expect(viaSource?.uuid).toBe(uuidFromDistinctId(teamId, target))
        expect(viaSource?.properties).toMatchObject({ born: 'yes' })
        expect(await divergences()).toBe(0)
        expect(await shadowErrors()).toBe(0)
    })

    it('an unseen target attaches to the one existing person, with the verdict-name divergence pinned', async () => {
        const source = id('attach-source')
        const target = id('attach-target')
        await createThroughBoth(source, { origin: 'source' }, batchId)

        const { result, mergeOps } = await runMerge(target, [source])

        // The existing person keeps surviving on both backends and only its
        // id set grows, but the verdict names differ by design: the saga
        // establishes the unresolved target first, so by execution both ids
        // share one person and it answers noop_same_person where Postgres's
        // one-exists branch says attached.
        expect(result.results[0]?.outcome).toBe('attached')
        expect(result.survivor?.uuid).toBe(uuidFromDistinctId(teamId, source))
        expect(await divergencesByField('outcome')).toBe(1)
        expect(await divergencesByField('survivor')).toBe(0)
        await applyMergeFollowUp(result, mergeOps, target)
        await routing.flush()
        routing.releaseBatch(batchId)
        await expectDurableRowParity(source)
        await expectDurableRowParity(target)

        batchId += 1
        const viaTarget = await routing.fetchForUpdate(teamId, target, batchId)
        expect(viaTarget?.uuid).toBe(uuidFromDistinctId(teamId, source))
        expect(await shadowErrors()).toBe(0)
    })

    it('a merge of two ids already on one person answers noop identically', async () => {
        const target = id('same-target')
        const source = id('same-source')
        await createThroughBoth(target, {}, batchId, [source])

        const { result } = await runMerge(target, [source])

        expect(result.results[0]?.outcome).toBe('noop_same_person')
        expect(result.survivor?.uuid).toBe(uuidFromDistinctId(teamId, target))
        expect(await divergences()).toBe(0)
        expect(await shadowErrors()).toBe(0)
    })

    it.each([
        [false, 'skipped_already_identified'],
        [true, 'merged'],
    ])(
        'an identified source with allowIdentifiedSources=%p answers %s on both backends',
        async (allowIdentifiedSources, expected) => {
            const target = id(`ident-${allowIdentifiedSources}-target`)
            const source = id(`ident-${allowIdentifiedSources}-source`)
            await createThroughBoth(target, {}, batchId)
            await createThroughBoth(source, {}, batchId, undefined, true)

            const { result, mergeOps } = await runMerge(target, [source], { allowIdentifiedSources })

            expect(result.results[0]?.outcome).toBe(expected)
            if (expected === 'merged') {
                await applyMergeFollowUp(result, mergeOps, target)
                await routing.flush()
                routing.releaseBatch(batchId)
                await expectDurableRowParity(target)
                await expectDurableRowParity(source)
            }
            expect(await divergences()).toBe(0)
            expect(await shadowErrors()).toBe(0)
        }
    )

    it('a two-source fold settles every verdict identically', async () => {
        const target = id('fold-target')
        const first = id('fold-first')
        const second = id('fold-second')
        await createThroughBoth(target, { origin: 'target' }, batchId)
        await createThroughBoth(first, { fromFirst: 'yes' }, batchId)
        await createThroughBoth(second, { fromSecond: 'yes' }, batchId)

        const { result, mergeOps } = await runMerge(target, [first, second], { set: { folded: 'yes' } })

        expect(result.foldAborted).toBeUndefined()
        expect(result.results.map((source) => source.outcome)).toEqual(['merged', 'merged'])
        expect(result.survivor?.uuid).toBe(uuidFromDistinctId(teamId, target))
        await applyMergeFollowUp(result, mergeOps, target)
        await routing.flush()
        routing.releaseBatch(batchId)
        await expectDurableRowParity(target)
        await expectDurableRowParity(first)
        await expectDurableRowParity(second)

        batchId += 1
        const viaFirst = await routing.fetchForUpdate(teamId, first, batchId)
        expect(viaFirst?.properties).toMatchObject({
            origin: 'target',
            fromFirst: 'yes',
            fromSecond: 'yes',
            folded: 'yes',
        })
        expect(await divergences()).toBe(0)
        expect(await shadowErrors()).toBe(0)
    })

    it('a replayed merge pins the one documented verdict divergence', async () => {
        const target = id('replay-target')
        const source = id('replay-source')
        await createThroughBoth(target, {}, batchId)
        await createThroughBoth(source, {}, batchId)
        const eventUuid = new UUIDT().toString()
        const sourceEventUuids = [new UUIDT().toString()]
        const { result: firstRun, mergeOps } = await runMerge(target, [source], { eventUuid, sourceEventUuids })
        expect(firstRun.results[0]?.outcome).toBe('merged')
        await applyMergeFollowUp(firstRun, mergeOps, target)
        await routing.flush()
        routing.releaseBatch(batchId)

        personhogStoreShadowDivergenceCounter.reset()
        batchId += 1
        // A redelivery of the same event: Postgres re-runs against moved
        // rows and lands on noop_same_person; the saga replays the recorded
        // 'merged' verdict per op id. Same survivor, different verdict
        // name — the one divergence this shape is allowed.
        const { result: replay } = await runMerge(target, [source], { eventUuid, sourceEventUuids })

        expect(replay.results[0]?.outcome).toBe('noop_same_person')
        expect(replay.survivor?.uuid).toBe(uuidFromDistinctId(teamId, target))
        expect(await divergencesByField('outcome')).toBe(1)
        expect(await divergencesByField('survivor')).toBe(0)
        expect(await shadowErrors()).toBe(0)
    })

    it('an over-limit source skips the merge in LIMIT mode, with the survivor divergence pinned', async () => {
        const target = id('limit-target')
        const source = id('limit-source')
        await createThroughBoth(target, {}, batchId)
        await createThroughBoth(source, {}, batchId, [id('limit-source-extra')])

        const { result } = await runMerge(target, [source], { mergeMode: { type: 'LIMIT', limit: 1 } })

        // Both backends skip on the same verdict; only the survivor field
        // differs by design — Postgres answers none on the skip, the saga
        // answers the target it resolved. The service maps the verdict to
        // an error either way, so nothing reads the survivor.
        expect(result.results[0]?.outcome).toBe('skipped_move_limit')
        expect(await divergencesByField('outcome')).toBe(0)
        expect(await divergencesByField('survivor')).toBe(1)
        expect(await shadowErrors()).toBe(0)
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
