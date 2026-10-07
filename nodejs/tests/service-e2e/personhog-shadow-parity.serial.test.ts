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
import { Code, ConnectError } from '@connectrpc/connect'
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
    personhogStoreShadowCreateRetriesCounter,
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
    let writeRepository: PersonHogPersonWriteRepository
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

    /**
     * One ingestion pod: its own caches over the shared databases and the
     * shared personhog cluster, so two pods can interleave on one person.
     * The personhog repository and the Postgres store can be wrapped, so a
     * test can fail one personhog call or run code between the two flushes.
     */
    const newPod = (
        repository: PersonHogPersonWriteRepository = writeRepository,
        wrapPg: (store: BatchWritingPersonsStore) => BatchWritingPersonsStore = (store) => store,
        pgRepository: PostgresPersonRepository = new PostgresPersonRepository(hub.postgres)
    ): RoutingPersonsStore =>
        new RoutingPersonsStore(
            wrapPg(
                new BatchWritingPersonsStore(pgRepository, outputs(), {
                    metricEmissionIntervalMs: 0,
                })
            ),
            new PersonhogPersonsStore(repository, {
                maxConcurrentUpdates: 10,
                updateAllProperties: false,
                syncMergeMoveLimit: 10_000,
            }),
            'shadow'
        )

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
        last_seen_at: string | null
    }

    const mainRowByDistinctId = async (distinctId: string): Promise<DurableRow | null> => {
        const { rows } = await hub.postgres.query<DurableRow>(
            PostgresUse.PERSONS_WRITE,
            `SELECT p.uuid, p.properties, p.is_identified,
                    (extract(epoch from p.created_at) * 1000)::bigint::text AS created_at,
                    (extract(epoch from p.last_seen_at) * 1000)::bigint::text AS last_seen_at
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
                    (extract(epoch from p.created_at) * 1000)::bigint::text AS created_at,
                    (extract(epoch from p.last_seen_at) * 1000)::bigint::text AS last_seen_at
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
                tmp.last_seen_at === main!.last_seen_at &&
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
        expect(tmp!.last_seen_at).toBe(main!.last_seen_at)
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
        writeRepository = new PersonHogPersonWriteRepository(
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
        routing = newPod()
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
        personhogStoreShadowCreateRetriesCounter.reset()
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

    it.each([['before'], ['after']])(
        "another pod's pending update to a merged-away id lands on the survivor when flushed %s the merge's own update",
        async (order) => {
            const target = id(`pods-${order}-target`)
            const source = id(`pods-${order}-source`)
            await createThroughBoth(target, { origin: 'target' }, batchId)
            await createThroughBoth(source, { origin: 'source', extra: 'source' }, batchId)

            // The other pod reads the source and holds an update to it, with
            // a newer last-seen, while this pod merges the source away. Its
            // flush finds no row for the person it cached: Postgres re-targets
            // from the distinct id, personhog redirects to the survivor.
            const other = newPod()
            const held = await other.fetchForUpdate(teamId, source, batchId)
            expect(held?.uuid).toBe(uuidFromDistinctId(teamId, source))
            const otherOps = ops({ $set: { fromOtherPod: 'yes' } })
            otherOps.lastSeenAtMs = DateTime.utc().plus({ hours: 1 }).startOf('hour').toMillis()
            await other.applyEventOps(held!, otherOps, source, batchId)

            const { result, mergeOps } = await runMerge(target, [source], { set: { mergedBy: 'this pod' } })
            expect(result.results[0]?.outcome).toBe('merged')
            if (order === 'before') {
                await other.flush()
            }
            await applyMergeFollowUp(result, mergeOps, target)
            await routing.flush()
            if (order === 'after') {
                await other.flush()
            }
            other.releaseBatch(batchId)
            routing.releaseBatch(batchId)

            batchId += 1
            const survivor = await routing.fetchForUpdate(teamId, target, batchId)
            expect(survivor?.properties).toMatchObject({
                origin: 'target',
                extra: 'source',
                mergedBy: 'this pod',
                fromOtherPod: 'yes',
            })
            expect(survivor?.last_seen_at?.toMillis()).toBe(otherOps.lastSeenAtMs)
            expect(await divergences()).toBe(0)
            expect(await shadowErrors()).toBe(0)
            await expectDurableRowParity(target)
            await expectDurableRowParity(source)
        }
    )

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

    /**
     * The shapes behind a shadow run's end-of-run drift: creates the shadow lost, and filtered
     * high-churn keys the two backends persisted under different rules.
     */
    describe('drift causes', () => {
        /** A pageview-shaped event: never forced, so the filtered-key rules apply. */
        const pageview = (properties: Record<string, unknown>) => ops(properties, '$pageview')

        const nextHourMs = () => DateTime.utc().plus({ hours: 1 }).startOf('hour').toMillis()

        /**
         * Fails the first get-or-create for `distinctId`. With `after`, identity first commits a stub
         * without its properties: what a cancellation between the stub commit and the property push leaves.
         */
        const failingCreateRepository = (
            distinctId: string,
            failure: () => Error,
            after = false
        ): PersonHogPersonWriteRepository => {
            let failed = false
            const real = writeRepository.getOrCreatePersonByDistinctId.bind(writeRepository)
            return new Proxy(writeRepository, {
                get(target, property, receiver) {
                    if (property !== 'getOrCreatePersonByDistinctId') {
                        return Reflect.get(target, property, receiver)
                    }
                    return async (entry: Parameters<typeof real>[0], callerTag?: string) => {
                        if (failed || entry.distinctId !== distinctId) {
                            return real(entry, callerTag)
                        }
                        failed = true
                        if (after) {
                            await real({ ...entry, setProperties: {}, setOnceProperties: {} }, callerTag)
                        }
                        throw failure()
                    }
                },
            })
        }

        const retriableUnavailable = (): Error =>
            Object.assign(new ConnectError('Server at capacity', Code.Unavailable), { isRetriable: true })

        /** A Postgres repository whose next batch write waits to be released, so a flush is caught with a write out. */
        const holdingPgRepository = () => {
            let holdNextWrite = false
            let releaseWrite: (() => void) | undefined
            const real = new PostgresPersonRepository(hub.postgres)
            const repository = new Proxy(real, {
                get(target, property, receiver) {
                    if (property !== 'updatePersonsBatch') {
                        return Reflect.get(target, property, receiver)
                    }
                    return async (...args: Parameters<PostgresPersonRepository['updatePersonsBatch']>) => {
                        if (holdNextWrite) {
                            holdNextWrite = false
                            await new Promise<void>((resolve) => (releaseWrite = resolve))
                        }
                        return real.updatePersonsBatch(...args)
                    }
                },
            })
            return {
                repository,
                holdNext: (): void => {
                    holdNextWrite = true
                },
                held: async (): Promise<void> => {
                    for (let waited = 0; releaseWrite === undefined && waited < 500; waited++) {
                        await new Promise((resolve) => setTimeout(resolve, 10))
                    }
                    expect(releaseWrite).toBeDefined()
                },
                release: (): void => releaseWrite!(),
            }
        }

        it.each([
            ['refused before identity committed', false, retriableUnavailable],
            ['cancelled after identity committed', true, () => new ConnectError('canceled', Code.Canceled)],
        ])('a shadow create %s still lands the person and its creation properties', async (_name, after, failure) => {
            const distinctId = id(`create-${after ? 'cancelled' : 'refused'}`)
            const pod = newPod(failingCreateRepository(distinctId, failure, after))
            await pod.createPerson(
                DateTime.utc(),
                { plan: 'free' },
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, distinctId),
                { distinctId },
                undefined,
                undefined,
                batchId
            )
            // The retry lands inside the create, so nothing is recorded as a shadow failure.
            expect(await shadowErrors()).toBe(0)
            expect(await counterTotal(personhogStoreShadowCreateRetriesCounter)).toBe(2)
            await pod.flush()
            pod.releaseBatch(batchId)

            // The next event for the id is an update, as Postgres already
            // holds the person; the shadow has to catch up on its own.
            batchId += 1
            const person = await pod.fetchForUpdate(teamId, distinctId, batchId)
            await pod.applyEventOps(person!, pageview({ $set: { visits: 2 } }), distinctId, batchId)
            await pod.flush()
            pod.releaseBatch(batchId)

            await expectDurableRowParity(distinctId)
        })

        it.each([
            ['a new key', (p: Record<string, unknown>) => pageview(p), { plan: 'pro' }],
            [
                'a last-seen advance',
                (p: Record<string, unknown>) => {
                    const advanced = pageview(p)
                    advanced.lastSeenAtMs = nextHourMs()
                    return advanced
                },
                {},
            ],
        ])(
            'a filtered-only change pending across an overlapping batch settles identically when %s follows',
            async (_name, trigger, triggerSet) => {
                const distinctId = id(`carry-${Object.keys(triggerSet).length}`)
                await createThroughBoth(distinctId, { $current_url: 'https://example.com/a' }, batchId)
                const first = batchId
                const person = await routing.fetchForUpdate(teamId, distinctId, first)
                await routing.applyEventOps(
                    person!,
                    pageview({ $set: { $current_url: 'https://example.com/b' } }),
                    distinctId,
                    first
                )
                // A second batch reads the person before the first is
                // released, so the cache entry outlives the first flush.
                batchId += 1
                const second = batchId
                const held = await routing.fetchForUpdate(teamId, distinctId, second)
                await routing.flush()
                routing.releaseBatch(first)

                await routing.applyEventOps(held!, trigger({ $set: triggerSet }), distinctId, second)
                await routing.flush()
                routing.releaseBatch(second)

                await expectDurableRowParity(distinctId)
            }
        )

        it('a forced event does not force later filtered-only flushes', async () => {
            const distinctId = id('sticky-force')
            await createThroughBoth(distinctId, { $browser_version: '1' }, batchId)
            const first = batchId
            const person = await routing.fetchForUpdate(teamId, distinctId, first)
            await routing.applyEventOps(person!, ops({ $set: { plan: 'x' } }), distinctId, first)
            batchId += 1
            const second = batchId
            const held = await routing.fetchForUpdate(teamId, distinctId, second)
            await routing.flush()
            routing.releaseBatch(first)

            await routing.applyEventOps(held!, pageview({ $set: { $browser_version: '2' } }), distinctId, second)
            await routing.flush()
            routing.releaseBatch(second)

            await expectDurableRowParity(distinctId)
        })

        it('a repeated array-valued property is not a change, so it promotes nothing', async () => {
            const distinctId = id('array-equality')
            await createThroughBoth(distinctId, { tags: ['a'], $current_url: 'https://example.com/a' }, batchId)
            const person = await routing.fetchForUpdate(teamId, distinctId, batchId)
            await routing.applyEventOps(
                person!,
                pageview({ $set: { tags: ['a'], $current_url: 'https://example.com/b' } }),
                distinctId,
                batchId
            )
            await routing.flush()
            routing.releaseBatch(batchId)

            await expectDurableRowParity(distinctId)
        })

        it('an event applied between the Postgres flush and the shadow flush is decided alike', async () => {
            const distinctId = id('flush-race')
            let betweenFlushes: (() => Promise<void>) | undefined
            const pod = newPod(writeRepository, (store) => {
                const flush = store.flush.bind(store)
                store.flush = async (beforeDecision?: Parameters<typeof flush>[0]) => {
                    const results = await flush(beforeDecision)
                    const hook = betweenFlushes
                    betweenFlushes = undefined
                    await hook?.()
                    return results
                }
                return store
            })
            await pod.createPerson(
                DateTime.utc(),
                { $current_url: 'https://example.com/a' },
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, distinctId),
                { distinctId },
                undefined,
                undefined,
                batchId
            )
            const first = batchId
            const person = await pod.fetchForUpdate(teamId, distinctId, first)
            await pod.applyEventOps(person!, pageview({ $set: { plan: 'pro' } }), distinctId, first)
            batchId += 1
            const second = batchId
            const held = await pod.fetchForUpdate(teamId, distinctId, second)
            // A concurrent batch's filtered-only event lands after Postgres
            // decided its write and before the shadow sent its segment.
            betweenFlushes = async () => {
                await pod.applyEventOps(
                    held!,
                    pageview({ $set: { $current_url: 'https://example.com/c' } }),
                    distinctId,
                    second
                )
            }
            await pod.flush()
            pod.releaseBatch(first)
            await pod.flush()
            pod.releaseBatch(second)

            await expectDurableRowParity(distinctId)
        })

        it('a repeat landing between the Postgres decision and the shadow write rejoins the group the next change promotes', async () => {
            const distinctId = id('declined-between')
            let betweenFlushes: (() => Promise<void>) | undefined
            const pod = newPod(writeRepository, (store) => {
                const flush = store.flush.bind(store)
                store.flush = async (beforeDecision?: Parameters<typeof flush>[0]) => {
                    const results = await flush(beforeDecision)
                    const hook = betweenFlushes
                    betweenFlushes = undefined
                    await hook?.()
                    return results
                }
                return store
            })
            await pod.createPerson(
                DateTime.utc(),
                { $current_url: 'https://example.com/a' },
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, distinctId),
                { distinctId },
                undefined,
                undefined,
                batchId
            )
            const first = batchId
            let person = await pod.fetchForUpdate(teamId, distinctId, first)
            await pod.applyEventOps(
                person!,
                pageview({ $set: { $current_url: 'https://example.com/b' } }),
                distinctId,
                first
            )
            batchId += 1
            const second = batchId
            // Postgres declined the filtered-only group and forgot the value. A concurrent batch re-sends it before
            // the shadow has written its segment, and Postgres lands it again.
            betweenFlushes = async () => {
                const reread = await pod.fetchForUpdate(teamId, distinctId, second)
                await pod.applyEventOps(
                    reread!,
                    pageview({ $set: { $current_url: 'https://example.com/b' } }),
                    distinctId,
                    second
                )
            }
            await pod.flush()
            pod.releaseBatch(first)
            person = await pod.fetchForUpdate(teamId, distinctId, second)
            await pod.applyEventOps(person!, pageview({ $set: { plan: 'pro' } }), distinctId, second)
            await pod.flush()
            pod.releaseBatch(second)

            await expectDurableRowParity(distinctId)
        })

        it('a set-once right behind a create that failed after identity committed yields to the creation value', async () => {
            const distinctId = id('create-order')
            const pod = newPod(
                failingCreateRepository(distinctId, () => new ConnectError('canceled', Code.Canceled), true)
            )
            await pod.createPerson(
                DateTime.utc(),
                { plan: 'free' },
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, distinctId),
                { distinctId },
                undefined,
                undefined,
                batchId
            )
            // The event behind the create in its distinct id's sequence: Postgres ignores the set-once.
            const person = await pod.fetchForUpdate(teamId, distinctId, batchId)
            await pod.applyEventOps(person!, ops({ $set_once: { plan: 'pro' } }), distinctId, batchId)
            await pod.flush()
            pod.releaseBatch(batchId)

            await expectDurableRowParity(distinctId)
        })

        it('a person first touched between the Postgres flush and the shadow flush waits for its own decision', async () => {
            const distinctId = id('late-lane')
            let betweenFlushes: (() => Promise<void>) | undefined
            const pod = newPod(writeRepository, (store) => {
                const flush = store.flush.bind(store)
                store.flush = async (beforeDecision?: Parameters<typeof flush>[0]) => {
                    const results = await flush(beforeDecision)
                    const hook = betweenFlushes
                    betweenFlushes = undefined
                    await hook?.()
                    return results
                }
                return store
            })
            const first = batchId
            await pod.createPerson(
                DateTime.utc(),
                { $current_url: 'https://example.com/a' },
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, distinctId),
                { distinctId },
                undefined,
                undefined,
                first
            )
            batchId += 1
            const second = batchId
            // A concurrent batch's first event for the person, a real change,
            // lands after Postgres decided and before the shadow flush.
            betweenFlushes = async () => {
                const person = await pod.fetchForUpdate(teamId, distinctId, second)
                await pod.applyEventOps(person!, pageview({ $set: { plan: 'pro' } }), distinctId, second)
            }
            await pod.flush()
            pod.releaseBatch(first)

            // That batch's filtered-only event follows before its own flush, so
            // Postgres weighs the two together.
            const person = await pod.fetchForUpdate(teamId, distinctId, second)
            await pod.applyEventOps(
                person!,
                pageview({ $set: { $current_url: 'https://example.com/c' } }),
                distinctId,
                second
            )
            await pod.flush()
            pod.releaseBatch(second)

            await expectDurableRowParity(distinctId)
        })

        it("a flush deciding while another flush's Postgres write is still out judges only what arrived since", async () => {
            const distinctId = id('in-flight-write')
            const pg = holdingPgRepository()
            const pod = newPod(writeRepository, (store) => store, pg.repository)
            await pod.createPerson(
                DateTime.utc(),
                { plan: 'free', $current_url: 'https://example.com/a' },
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, distinctId),
                { distinctId },
                undefined,
                undefined,
                batchId
            )
            const first = batchId
            const person = await pod.fetchForUpdate(teamId, distinctId, first)
            await pod.applyEventOps(person!, pageview({ $set: { plan: 'pro' } }), distinctId, first)
            pg.holdNext()
            const flushing = pod.flush()
            await pg.held()

            // Another batch's filtered-only event and flush land while that write is still out.
            batchId += 1
            const second = batchId
            const held = await pod.fetchForUpdate(teamId, distinctId, second)
            await pod.applyEventOps(
                held!,
                pageview({ $set: { $current_url: 'https://example.com/c' } }),
                distinctId,
                second
            )
            const secondFlush = pod.flush()
            pg.release()
            await Promise.all([flushing, secondFlush])
            pod.releaseBatch(first)
            pod.releaseBatch(second)

            await expectDurableRowParity(distinctId)
        })

        it("an event arriving while a flush waits on the person's write out is judged with that flush's decision alike", async () => {
            const distinctId = id('between-rounds')
            const pg = holdingPgRepository()
            const pod = newPod(writeRepository, (store) => store, pg.repository)
            await pod.createPerson(
                DateTime.utc(),
                { plan: 'free', $current_url: 'https://example.com/a' },
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, distinctId),
                { distinctId },
                undefined,
                undefined,
                batchId
            )
            const first = batchId
            const person = await pod.fetchForUpdate(teamId, distinctId, first)
            await pod.applyEventOps(person!, pageview({ $set: { plan: 'pro' } }), distinctId, first)
            pg.holdNext()
            const flushing = pod.flush()
            await pg.held()

            // Another batch's filtered-only event, then its flush, which waits on the write out.
            batchId += 1
            const second = batchId
            const held = await pod.fetchForUpdate(teamId, distinctId, second)
            await pod.applyEventOps(
                held!,
                pageview({ $set: { $current_url: 'https://example.com/b' } }),
                distinctId,
                second
            )
            const secondFlush = pod.flush()
            // A real change lands while that flush waits; Postgres decides both events together in its next round.
            await pod.applyEventOps(held!, pageview({ $set: { plan: 'max' } }), distinctId, second)
            pg.release()
            await Promise.all([flushing, secondFlush])
            pod.releaseBatch(first)
            pod.releaseBatch(second)

            await expectDurableRowParity(distinctId)
        })

        it('a repeat of a filtered value between a filtered change and a real change leaves the group whole', async () => {
            const distinctId = id('repeat-between')
            await createThroughBoth(distinctId, { $current_url: 'https://example.com/a' }, batchId)
            let person = await routing.fetchForUpdate(teamId, distinctId, batchId)
            await routing.applyEventOps(
                person!,
                pageview({ $set: { $current_url: 'https://example.com/b' } }),
                distinctId,
                batchId
            )
            // A click on the same page repeats the URL; Postgres lands nothing for it and the group stays one.
            person = await routing.fetchForUpdate(teamId, distinctId, batchId)
            await routing.applyEventOps(
                person!,
                pageview({ $set: { $current_url: 'https://example.com/b' } }),
                distinctId,
                batchId
            )
            person = await routing.fetchForUpdate(teamId, distinctId, batchId)
            await routing.applyEventOps(person!, pageview({ $set: { plan: 'pro' } }), distinctId, batchId)
            await routing.flush()
            routing.releaseBatch(batchId)

            await expectDurableRowParity(distinctId)
        })

        it('a forced event that changes nothing does not force the group on either store', async () => {
            const distinctId = id('forced-noop')
            await createThroughBoth(distinctId, { $browser: 'Chrome', plan: 'free' }, batchId)
            let person = await routing.fetchForUpdate(teamId, distinctId, batchId)
            await routing.applyEventOps(person!, pageview({ $set: { $browser: 'Firefox' } }), distinctId, batchId)
            // A server-side $set of a value the row already holds: Postgres lands nothing, so its force reaches no group.
            person = await routing.fetchForUpdate(teamId, distinctId, batchId)
            await routing.applyEventOps(person!, ops({ $set: { plan: 'free' } }), distinctId, batchId)
            await routing.flush()
            routing.releaseBatch(batchId)

            await expectDurableRowParity(distinctId)
        })

        it('two distinct ids of one person interleaved in one batch judge a repeat alike', async () => {
            const first = id('two-ids-1')
            const second = id('two-ids-2')
            await createThroughBoth(first, { $browser: 'Chrome' }, batchId, [second])
            // The second id's event read the person before the first id's change landed, so Postgres sees its repeat
            // as a change against that snapshot and lands it again.
            const stale = await routing.fetchForUpdate(teamId, second, batchId)
            const fresh = await routing.fetchForUpdate(teamId, first, batchId)
            await routing.applyEventOps(fresh!, pageview({ $set: { $browser: 'Firefox' } }), first, batchId)
            await routing.applyEventOps(stale!, pageview({ $set: { $browser: 'Firefox' } }), second, batchId)
            const person = await routing.fetchForUpdate(teamId, second, batchId)
            await routing.applyEventOps(person!, pageview({ $set: { plan: 'pro' } }), second, batchId)
            await routing.flush()
            routing.releaseBatch(batchId)

            await expectDurableRowParity(first)
        })

        it('a forced repeat of a filtered value still pending is written by both stores', async () => {
            const distinctId = id('forced-repeat')
            await createThroughBoth(distinctId, { $browser: 'Firefox' }, batchId)
            let person = await routing.fetchForUpdate(teamId, distinctId, batchId)
            await routing.applyEventOps(person!, pageview({ $set: { $browser: 'Safari' } }), distinctId, batchId)
            // Each event reads the view as its store holds it; the identify-shaped repeat changes nothing against it,
            // and its force has to reach the pending group on both sides.
            person = await routing.fetchForUpdate(teamId, distinctId, batchId)
            await routing.applyEventOps(person!, ops({ $set: { $browser: 'Safari' } }), distinctId, batchId)
            await routing.flush()
            routing.releaseBatch(batchId)

            await expectDurableRowParity(distinctId)
        })

        it('a filtered value an ignored flush declined is written when a real change follows it', async () => {
            const distinctId = id('declined-then-promoted')
            await createThroughBoth(distinctId, { $current_url: 'https://example.com/a' }, batchId)
            let person = await routing.fetchForUpdate(teamId, distinctId, batchId)
            await routing.applyEventOps(
                person!,
                pageview({ $set: { $current_url: 'https://example.com/b' } }),
                distinctId,
                batchId
            )
            // Both stores decline the filtered-only group; the batch still references the person.
            await routing.flush()

            // Both views must have reverted to the row, so the repeat is a change again that joins the pending group,
            // and the real change that follows promotes it on both sides.
            person = await routing.fetchForUpdate(teamId, distinctId, batchId)
            await routing.applyEventOps(
                person!,
                pageview({ $set: { $current_url: 'https://example.com/b' } }),
                distinctId,
                batchId
            )
            person = await routing.fetchForUpdate(teamId, distinctId, batchId)
            await routing.applyEventOps(person!, pageview({ $set: { plan: 'pro' } }), distinctId, batchId)
            await routing.flush()
            routing.releaseBatch(batchId)

            await expectDurableRowParity(distinctId)
        })

        it('a filtered-only event right behind a retried create that found a stub is weighed alone', async () => {
            const distinctId = id('reconcile-fold')
            const pod = newPod(
                failingCreateRepository(distinctId, () => new ConnectError('canceled', Code.Canceled), true)
            )
            await pod.createPerson(
                DateTime.utc(),
                { $current_url: 'https://example.com/a' },
                {},
                {},
                teamId,
                null,
                false,
                uuidFromDistinctId(teamId, distinctId),
                { distinctId },
                undefined,
                undefined,
                batchId
            )
            // The creation properties were applied by the retry; Postgres judges this event on its own.
            const person = await pod.fetchForUpdate(teamId, distinctId, batchId)
            await pod.applyEventOps(
                person!,
                pageview({ $set: { $current_url: 'https://example.com/b' } }),
                distinctId,
                batchId
            )
            await pod.flush()
            pod.releaseBatch(batchId)

            await expectDurableRowParity(distinctId)
        })
    })
})
