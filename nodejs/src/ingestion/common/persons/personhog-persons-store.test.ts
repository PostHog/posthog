import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import { PersonhogPropertiesSizeError } from '~/common/personhog/persons'
import { PersonClaimedByLifecycleOpError } from '~/common/persons/repositories/person-repository'
import { NoRowsUpdatedError } from '~/common/utils/utils'
import { InternalPerson } from '~/types'

import { PersonMergeCallFailedError, createDefaultSyncMergeMode } from './person-merge-types'
import { extractEventOps } from './person-update'
import { mergeOpIdFromRequest } from './person-uuid'
import {
    PersonhogPendingRpcError,
    PersonhogPersonsStore,
    personhogStoreFenceCounter,
    personhogStoreFlushCounter,
} from './personhog-persons-store'

describe('PersonhogPersonsStore', () => {
    let repository: jest.Mocked<PersonHogPersonWriteRepository>
    let store: PersonhogPersonsStore
    let person: InternalPerson

    const ops = (properties: Record<string, unknown>, event = '$set') =>
        extractEventOps({
            event,
            distinct_id: 'd1',
            properties,
            team_id: 1,
            uuid: 'event-uuid',
            ip: null,
            now: '2026-08-07T00:00:00Z',
            site_url: '',
        } as any)

    beforeEach(() => {
        person = {
            id: '7',
            uuid: 'person-uuid',
            team_id: 1,
            properties: { plan: 'free' },
            created_at: DateTime.fromMillis(3_600_000, { zone: 'utc' }),
            version: 1,
            properties_last_updated_at: {},
            properties_last_operation: {},
            is_user_id: null,
            is_identified: false,
            last_seen_at: null,
        }
        repository = {
            resolvePersonsByDistinctIds: jest.fn().mockResolvedValue([]),
            fetchPersonById: jest.fn().mockResolvedValue(null),
            // An applied write bumps the version, as the leader does.
            updatePersonProperties: jest.fn().mockResolvedValue({ person: { ...person, version: 2 }, updated: true }),
            getDistinctIdsForPersons: jest.fn().mockResolvedValue({}),
            getOrCreatePersonByDistinctId: jest.fn().mockResolvedValue({ person, created: true }),
        } as unknown as jest.Mocked<PersonHogPersonWriteRepository>
        store = new PersonhogPersonsStore(repository)
    })

    it.each([0, -1, 1.5])('refuses a sync merge move limit of %p at construction', (syncMergeMoveLimit) => {
        // Below 1 the saga skips every merge; a non-integer throws a RangeError
        // inside BigInt() at merge time. Both lose merges deployment-wide.
        expect(() => new PersonhogPersonsStore(repository, { syncMergeMoveLimit })).toThrow(
            'PERSONHOG_SYNC_MERGE_MOVE_LIMIT must be an integer >= 1'
        )
    })

    it('keeps an entry writable when the redirect resolve fails transiently', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        repository.updatePersonProperties.mockRejectedValueOnce(new NoRowsUpdatedError('merged away') as never)
        repository.resolvePersonsByDistinctIds.mockRejectedValue(new Error('identity unavailable') as never)

        await expect(bound.flush()).rejects.toThrow('identity unavailable')

        // A throw skips the success path, so an in-flight mark left set would
        // make every later pass skip this entry and strand its ops.
        // Cleared so only a fresh write on the second pass can satisfy this.
        repository.updatePersonProperties.mockClear()
        repository.updatePersonProperties.mockResolvedValue({ person, updated: true } as never)
        repository.resolvePersonsByDistinctIds.mockResolvedValue([])
        await bound.flush()
        expect(repository.updatePersonProperties).toHaveBeenCalledWith(
            expect.objectContaining({ setProperties: { a: '1' } }),
            expect.any(String)
        )
    })

    it('ops folded during a write land behind it rather than in it', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        let releaseWrite: () => void = () => {}
        let writeStarted: () => void = () => {}
        const writing = new Promise<void>((resolve) => {
            writeStarted = resolve
        })
        repository.updatePersonProperties.mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    writeStarted()
                    releaseWrite = () => resolve({ person, updated: true } as never)
                }) as never
        )

        const flushing = bound.flush()
        await writing
        // Folded while the first payload is on the wire: merging into it
        // would change what is being sent, and truncating the snapshot
        // afterwards would take this event with it.
        await bound.applyEventOps(person, ops({ $set: { b: '2' } }), 'd1')
        releaseWrite()
        await flushing

        expect(repository.updatePersonProperties.mock.calls[0][0].setProperties).toEqual({ a: '1' })

        repository.updatePersonProperties.mockClear()
        await bound.flush()
        expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
        expect(repository.updatePersonProperties.mock.calls[0][0].setProperties).toEqual({ b: '2' })
    })

    it('a fold waits for a merge holding its person, then lands behind it', async () => {
        personhogStoreFenceCounter.reset()
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
        repository.fetchPersonById.mockResolvedValue({ ...person } as never)
        const bound = store.forBatch(0)
        await bound.fetchForUpdate(1, 'd1')

        let releaseMerge: () => void = () => {}
        let mergeStarted: () => void = () => {}
        const merging = new Promise<void>((resolve) => {
            mergeStarted = resolve
        })
        repository.mergePersons = jest.fn().mockImplementation(
            () =>
                new Promise((resolve) => {
                    mergeStarted()
                    releaseMerge = () => resolve({ survivor: null, results: [] })
                })
        )

        const merge = bound.mergePersons({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
            eventOps: ops({}, '$identify'),
            opId: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })
        await merging
        // The fence installs after the merge's own resolve; wait for it.
        await new Promise((resolve) => setTimeout(resolve, 0))

        // Folding now would put these ops behind a request already on the
        // wire, where they would land after the merge rather than in it.
        let folded = false
        const fold = bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1').then(() => {
            folded = true
        })
        await Promise.resolve()
        expect(folded).toBe(false)

        releaseMerge()
        await merge
        await fold
        expect(folded).toBe(true)
        // The wait has to end by release, not by the timeout: a fence left
        // standing would still let this fold through, just seconds later.
        const waits = (await personhogStoreFenceCounter.get()).values
        expect(waits.map((wait) => wait.labels.outcome)).toEqual(['released'])
    })

    it('folds a batch of ops into one leader call per person and publishes nothing', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' }, $set_once: { first: 'x' } }), 'd1')
        await bound.applyEventOps(person, ops({ $set: { a: '2', first: 'shadowed' } }), 'd1')
        await bound.applyEventOps(person, ops({ $unset: ['gone'] }), 'd1')

        const results = await bound.flush()

        expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
        const sent = repository.updatePersonProperties.mock.calls[0][0]
        expect(sent.personId).toEqual('7')
        expect(sent.setProperties).toEqual({ a: '2', first: 'shadowed' })
        expect(sent.setOnceProperties).toEqual({})
        expect(sent.unsetProperties).toEqual(['gone'])
        // The changelog is this backend's ClickHouse feed: a flush writes
        // segments and publishes nothing.
        expect(results).toEqual([])
    })

    it('returns a locally projected person while the leader stays authoritative at flush', async () => {
        const bound = store.forBatch(0)
        const eventOps = ops({ $set: { plan: 'pro' }, $set_once: { plan: 'ignored', fresh: 'kept' } })
        eventOps.isIdentified = true
        eventOps.lastSeenAtMs = 7_200_000

        const [projected, messages] = await bound.applyEventOps(person, eventOps, 'd1')

        expect(messages).toEqual([])
        expect(projected.properties).toEqual({ plan: 'pro', fresh: 'kept' })
        expect(projected.is_identified).toBe(true)
        expect(projected.last_seen_at?.toMillis()).toEqual(7_200_000)
        expect(person.properties).toEqual({ plan: 'free' })
    })

    describe('flush suppression of filtered-only lanes', () => {
        it('a lane of unforced filtered-only changes never reaches the leader', async () => {
            person.properties = { $browser: 'Firefox' }
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { $browser: 'Chrome' } }, 'pageview'), 'd1')
            const results = await bound.flush()
            expect(repository.updatePersonProperties).not.toHaveBeenCalled()
            expect(results).toEqual([])
        })

        it.each([
            ['a person event forces the write', { $browser: 'Firefox' }, { $set: { $browser: 'Chrome' } }, '$set'],
            ['a new key always counts', {}, { $set: { $browser: 'Chrome' } }, 'pageview'],
            ['an unset always counts', { $browser: 'Firefox' }, { $unset: ['$browser'] }, 'pageview'],
        ])('%s and the lane writes', async (_label, baseline, props, event) => {
            person.properties = { ...(baseline as Record<string, string>) }
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops(props as Record<string, unknown>, event as string), 'd1')
            await bound.flush()
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
        })

        it('a scalar move writes without property changes', async () => {
            const bound = store.forBatch(0)
            const scalarOnly = ops({}, 'pageview')
            scalarOnly.isIdentified = true
            await bound.applyEventOps(person, scalarOnly, 'd1')
            await bound.flush()
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
        })

        it('one update-worthy event makes the whole lane write', async () => {
            person.properties = { $browser: 'Firefox' }
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { $browser: 'Chrome' } }, 'pageview'), 'd1')
            await bound.applyEventOps(person, ops({ $set: { plan: 'pro' } }, 'pageview'), 'd1')
            await bound.flush()
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
        })
    })

    it('does not fold denied events', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }, '$exception'), 'd1')
        const results = await bound.flush()
        expect(repository.updatePersonProperties).not.toHaveBeenCalled()
        expect(results).toEqual([])
    })

    it('a denied event still writes its scalars, without its properties', async () => {
        const bound = store.forBatch(0)
        const denied = ops({ $set: { a: '1' } }, '$exception')
        denied.lastSeenAtMs = 7_200_000
        const [projected] = await bound.applyEventOps(person, denied, 'd1')
        expect(projected.last_seen_at?.toMillis()).toBe(7_200_000)
        expect(projected.properties).toEqual({ plan: 'free' })

        await bound.flush()
        const sent = repository.updatePersonProperties.mock.calls[0][0]
        expect(sent.lastSeenAtMs).toBe(7_200_000)
        expect(sent.setProperties).toEqual({})
    })

    it('memoizes update fetches per batch, resolving once and reading state once', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        const bound = store.forBatch(0)
        await bound.fetchForUpdate(1, 'd1')
        await bound.fetchForUpdate(1, 'd1')
        expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(1)
        expect(repository.fetchPersonById).toHaveBeenCalledTimes(1)
    })

    it('update fetches take state from the leader, not the resolution', async () => {
        // The identity resolve returns writer-applied state; the leader's
        // is fresher and must win as the projection baseline.
        repository.resolvePersonsByDistinctIds.mockResolvedValue([
            { teamId: 1, distinctId: 'd1', person: { ...person, properties: { plan: 'stale' } } },
        ])
        repository.fetchPersonById.mockResolvedValue({ ...person, properties: { plan: 'fresh' }, version: 9 })
        const bound = store.forBatch(0)
        const fetched = await bound.fetchForUpdate(1, 'd1')
        expect(fetched?.properties).toEqual({ plan: 'fresh' })
        expect(fetched?.version).toBe(9)
        expect(repository.fetchPersonById).toHaveBeenCalledWith(1, '7', expect.any(String))
    })

    it('checking fetches use the resolved person without a leader call', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        const bound = store.forBatch(0)
        const fetched = await bound.fetchForChecking(1, 'd1')
        expect(fetched?.id).toBe('7')
        expect(repository.fetchPersonById).not.toHaveBeenCalled()
    })

    it('prefetch resolves the batch once so later fetches make no calls', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        await store.prefetchPersons([{ teamId: 1, distinctId: 'd1', batchId: 0 }])
        const bound = store.forBatch(0)
        const fetched = await bound.fetchForUpdate(1, 'd1')
        expect(fetched?.id).toBe('7')
        expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(1)
        expect(repository.fetchPersonById).toHaveBeenCalledTimes(1)
    })

    it('a stale null result cannot downgrade a live mapping', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        const bound = store.forBatch(0)
        const fetched = await bound.fetchForUpdate(1, 'd1')
        expect(fetched?.id).toBe('7')

        // A late prefetch response reporting absence must not erase the
        // resolved mapping.
        ;(store as any).memo.record(1, 'd1', null, 0)
        const again = await bound.fetchForUpdate(1, 'd1')
        expect(again?.id).toBe('7')
    })

    it('prefetch dedupes repeated distinct ids before resolving', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        await store.prefetchPersons([
            { teamId: 1, distinctId: 'd1', batchId: 0 },
            { teamId: 1, distinctId: 'd1', batchId: 0 },
            { teamId: 1, distinctId: 'd1', batchId: 0 },
        ])
        expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(1)
        expect(repository.resolvePersonsByDistinctIds.mock.calls[0][0]).toEqual([{ teamId: 1, distinctId: 'd1' }])
    })

    it('a failed prefetch falls back to first-touch resolution', async () => {
        repository.resolvePersonsByDistinctIds.mockRejectedValueOnce(new Error('identity unavailable'))
        await store.prefetchPersons([{ teamId: 1, distinctId: 'd1', batchId: 0 }])
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        const bound = store.forBatch(0)
        const fetched = await bound.fetchForUpdate(1, 'd1')
        expect(fetched?.id).toBe('7')
    })

    describe('mergePersons runs the saga and folds it into the batch view', () => {
        const survivor = () => ({ ...person, id: '7', properties: { plan: 'merged' }, version: 5 })

        beforeEach(() => {
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: survivor(),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
            })
        })

        const mergeRequest = () => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
            eventOps: ops({ $set: { plan: 'pro' } }, '$identify'),
            opId: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('a FAILED_PRECONDITION refusal salts the retry op id with the payload fingerprint', async () => {
            // A recorded op refuses a drifted redelivery forever under one
            // op id (payloads legitimately drift — GeoIP refreshes,
            // transformation stamps), so the retry must run as a fresh op,
            // which settles as a no-op when the recorded merge committed.
            const opIds: string[] = []
            repository.mergePersons = jest.fn().mockImplementation((call: { opId: string }) => {
                opIds.push(call.opId)
                if (opIds.length === 1) {
                    return Promise.reject(
                        new ConnectError('op_id was already used for a different request', Code.FailedPrecondition)
                    )
                }
                return Promise.resolve({
                    survivor: survivor(),
                    results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                })
            })
            const bound = store.forBatch(0)

            const result = await bound.mergePersons(mergeRequest())

            expect(result.survivor?.version).toBe(5)
            expect(opIds).toHaveLength(2)
            expect(opIds[1]).not.toBe(opIds[0])

            // The salt is the payload fingerprint, not an attempt counter:
            // a counter restarts every delivery, so a few payload-drifting
            // redeliveries exhaust its reachable op ids and the merge
            // wedges behind recorded mismatches forever. The fingerprint is
            // stable, so a repeat delivery with the same payload derives
            // the same salted op and attaches to what it recorded.
            const firstDelivery = [...opIds]
            opIds.length = 0
            await bound.mergePersons(mergeRequest())
            expect(opIds).toEqual(firstDelivery)
        })

        it('a conflict gets the full salted retry budget before surfacing as the claim error', async () => {
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: null,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'skipped_conflict' }],
            })
            const bound = store.forBatch(0)

            await expect(bound.mergePersons(mergeRequest())).rejects.toBeInstanceOf(PersonClaimedByLifecycleOpError)

            // A saga-aborted conflict is recorded terminally and replays
            // under its op id even after the holding operation cleared, so
            // every retry presents a fresh salted identity for a real
            // second look. Safe: a conflict verdict proves nothing was
            // destroyed, so a fresh op cannot double-merge.
            const opIds = (repository.mergePersons as jest.Mock).mock.calls.map(([call]) => call.opId)
            expect(opIds).toHaveLength(3)
            expect(new Set(opIds).size).toBe(3)
        })

        it('a conflict that clears on a salted retry merges normally', async () => {
            repository.mergePersons = jest
                .fn()
                .mockResolvedValueOnce({
                    survivor: null,
                    results: [{ sourceDistinctId: 'anon-1', outcome: 'skipped_conflict' }],
                })
                .mockResolvedValueOnce({
                    survivor: survivor(),
                    results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                })
            const bound = store.forBatch(0)

            const result = await bound.mergePersons(mergeRequest())

            expect(result.survivor?.version).toBe(5)
            const [first, second] = (repository.mergePersons as jest.Mock).mock.calls.map(([call]) => call.opId)
            expect(second).not.toBe(first)
        })

        it('later fetches of the touched ids read the survivor without re-resolving', async () => {
            const bound = store.forBatch(0)
            const result = await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({ $set: { plan: 'pro' } }, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })
            expect(result.survivor?.properties).toEqual({ plan: 'merged' })
            // The store owns the saga's move-limit policy: SYNC mode sends
            // its configured guard, and the event ops carry the property sets.
            // The op id is team-scoped, never the raw client-supplied event
            // uuid, so one team's uuid cannot collide with another team's op.
            expect(repository.mergePersons).toHaveBeenCalledWith(
                expect.objectContaining({
                    moveLimit: 10_000,
                    eventSet: { plan: 'pro' },
                    eventSetOnce: {},
                    opId: mergeOpIdFromRequest(1, 'event-uuid', ['anon-1'], 10_000),
                }),
                expect.any(String)
            )

            repository.resolvePersonsByDistinctIds.mockClear()
            const viaTarget = await bound.fetchForUpdate(1, 'd1')
            const viaSource = await bound.fetchForUpdate(1, 'anon-1')
            expect(viaTarget?.version).toBe(5)
            expect(viaSource?.version).toBe(5)
            expect(repository.resolvePersonsByDistinctIds).not.toHaveBeenCalled()
        })

        it.each([
            [{ type: 'LIMIT' as const, limit: 123 }, 123],
            [{ type: 'ASYNC' as const, limit: 456 }, 456],
        ])('mode %o carries its own limit as the saga move limit', async (mergeMode, expectedMoveLimit) => {
            const bound = store.forBatch(0)
            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode,
                createdAtMs: 3_600_000,
            })
            expect(repository.mergePersons).toHaveBeenCalledWith(
                expect.objectContaining({ moveLimit: expectedMoveLimit }),
                expect.any(String)
            )
        })

        it('purges every resolution of a merged-away person, not just the named source', async () => {
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '9' } as never)
            const bound = store.forBatch(0)
            await bound.fetchForUpdate(1, 'anon-1')
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'anon-1-alias', person: { ...person, id: '9' } },
            ] as never)
            await bound.fetchForUpdate(1, 'anon-1-alias')

            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })
            repository.resolvePersonsByDistinctIds.mockClear()

            // The alias resolved to the merged-away person. It now belongs to
            // the survivor, and reading it must not answer the dead person.
            const seen = await bound.fetchForUpdate(1, 'anon-1-alias')
            expect(seen?.id).toBe('7')
            expect(repository.resolvePersonsByDistinctIds).not.toHaveBeenCalled()
        })

        it('a skipped source keeps its existing resolution', async () => {
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ])
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '9' })
            const bound = store.forBatch(0)
            await bound.fetchForUpdate(1, 'anon-1')
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: survivor(),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'skipped_already_identified' }],
            })

            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })
            repository.resolvePersonsByDistinctIds.mockClear()

            // Reconciliation is keyed on the persons the merge destroyed, so a
            // skipped source's person is untouched and its resolution stands.
            const viaSource = await bound.fetchForUpdate(1, 'anon-1')
            expect(viaSource?.id).toBe('9')
            expect(repository.resolvePersonsByDistinctIds).not.toHaveBeenCalled()
        })

        it('invalidates the batch view when the saga call fails', async () => {
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '9' } as never)
            const bound = store.forBatch(0)
            await bound.fetchForUpdate(1, 'anon-1')
            repository.mergePersons = jest.fn().mockRejectedValue(new Error('saga unreachable'))
            repository.resolvePersonsByDistinctIds.mockClear()

            await expect(
                bound.mergePersons({
                    teamId: 1,
                    targetDistinctId: 'd1',
                    sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                    eventOps: ops({}, '$identify'),
                    opId: 'event-uuid',
                    allowIdentifiedSources: false,
                    mergeMode: createDefaultSyncMergeMode(),
                    createdAtMs: 3_600_000,
                })
            ).rejects.toThrow(PersonMergeCallFailedError)
            repository.resolvePersonsByDistinctIds.mockClear()

            // The saga persists each step, so a failed call may still have
            // flipped the ids; the memo cannot be trusted afterwards.
            await bound.fetchForUpdate(1, 'anon-1')
            expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(1)
        })

        it('purges a resolution under an id the request never named, via the reported person', async () => {
            // Only the person id reaches this: the batch resolved the person
            // under anon-2, and the merge names anon-1, so there is no memo
            // entry to discover the dead person key from.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-2', person: { ...person, id: '9' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '9' } as never)
            const bound = store.forBatch(0)
            await bound.fetchForUpdate(1, 'anon-2')

            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })
            repository.resolvePersonsByDistinctIds.mockClear()

            const seen = await bound.fetchForUpdate(1, 'anon-2')
            expect(seen?.id).toBe('7')
            expect(repository.resolvePersonsByDistinctIds).not.toHaveBeenCalled()
        })

        it('still purges by named distinct id when the merge reports no person', async () => {
            // Older servers and op rows written before the field replay with
            // no person id; reconciliation has to fall back rather than stop.
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: survivor(),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
            })
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '9' } as never)
            const bound = store.forBatch(0)
            await bound.fetchForUpdate(1, 'anon-1')
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'anon-1-alias', person: { ...person, id: '9' } },
            ] as never)
            await bound.fetchForUpdate(1, 'anon-1-alias')

            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })
            repository.resolvePersonsByDistinctIds.mockClear()

            // With no server-named person the dead set is inferred from
            // this store's own memo, which a replay or a cross-pod merge
            // can make stale — so the alias is released to re-resolve
            // rather than repointed on inference alone.
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'anon-1-alias', person: { ...person, id: '7' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '7' } as never)
            const seen = await bound.fetchForUpdate(1, 'anon-1-alias')
            expect(seen?.id).toBe('7')
            expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(1)
        })
    })

    it('creation resolves through identity and memoizes every distinct id it mapped', async () => {
        const bound = store.forBatch(0)
        const result = await bound.createPerson(
            DateTime.fromMillis(3_600_000, { zone: 'utc' }),
            { initial: 'props' },
            {},
            {},
            1,
            null,
            false,
            'advisory-uuid',
            { distinctId: 'd1' },
            [{ distinctId: 'd2' }]
        )

        expect(result.success).toBe(true)
        expect(repository.getOrCreatePersonByDistinctId).toHaveBeenCalledWith(
            expect.objectContaining({
                teamId: 1,
                distinctId: 'd1',
                extraDistinctIds: ['d2'],
                setProperties: { initial: 'props' },
                createdAtMs: 3_600_000,
            }),
            expect.any(String)
        )
        await bound.fetchForUpdate(1, 'd1')
        await bound.fetchForUpdate(1, 'd2')
        expect(repository.resolvePersonsByDistinctIds).not.toHaveBeenCalled()
    })

    it('a create that finds an existing person leaves its id readable for updates', async () => {
        // The found branch pays a leader read to get current state. That
        // state satisfies the update read class, so the id it resolves must
        // be recorded as such — otherwise the next update fetch re-resolves
        // and re-reads the leader for state this call already holds.
        repository.getOrCreatePersonByDistinctId.mockResolvedValue({ person, created: false } as never)
        repository.fetchPersonById.mockResolvedValue({ ...person, properties: { plan: 'fresh' } } as never)
        const bound = store.forBatch(0)

        await bound.createPerson(
            DateTime.fromMillis(3_600_000, { zone: 'utc' }),
            {},
            {},
            {},
            1,
            null,
            false,
            'advisory-uuid',
            { distinctId: 'd1' },
            undefined
        )
        repository.resolvePersonsByDistinctIds.mockClear()
        repository.fetchPersonById.mockClear()

        const fetched = await bound.fetchForUpdate(1, 'd1')

        expect(fetched?.properties).toEqual({ plan: 'fresh' })
        expect(repository.resolvePersonsByDistinctIds).not.toHaveBeenCalled()
        expect(repository.fetchPersonById).not.toHaveBeenCalled()
    })

    it.each([
        ['not_found', new NoRowsUpdatedError('gone')],
        ['size_violation', new PersonhogPropertiesSizeError('too big', 1, '7')],
    ])('drops %s from the lane rather than failing or retrying it forever', async (_outcome, error) => {
        repository.updatePersonProperties.mockRejectedValue(error)
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        await bound.flush()

        // The leader can never accept this payload, so leaving it in the
        // lane would re-send it on every pass for the rest of the batch.
        repository.updatePersonProperties.mockClear()
        await bound.flush()
        expect(repository.updatePersonProperties).not.toHaveBeenCalled()
    })

    it('redirects a merged-away lane to the survivor at flush', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        repository.updatePersonProperties
            .mockRejectedValueOnce(new NoRowsUpdatedError('merged away'))
            .mockResolvedValue({ person: { ...person, id: '9', version: 3 }, updated: true } as never)
        repository.resolvePersonsByDistinctIds.mockResolvedValue([
            { teamId: 1, distinctId: 'd1', person: { ...person, id: '9' } },
        ] as never)

        await bound.flush()

        expect(repository.updatePersonProperties).toHaveBeenLastCalledWith(
            expect.objectContaining({ personId: '9', setProperties: { a: '1' } }),
            expect.any(String)
        )
    })

    it('redirects a merged-away person’s ops with source precedence', async () => {
        const bound = store.forBatch(0)
        repository.mergePersons = jest.fn().mockResolvedValue({
            survivor: { ...person, id: '7' },
            results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
        })
        // Folded for the person this merge is about to destroy, so these ops
        // logically precede it and must not overwrite what it decided.
        await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'stale' }, $unset: ['gone'] }), 'anon-2')
        await bound.mergePersons({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
            eventOps: ops({}, '$identify'),
            opId: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        repository.updatePersonProperties
            .mockRejectedValueOnce(new NoRowsUpdatedError('merged away') as never)
            .mockResolvedValue({ person, updated: true } as never)
        repository.resolvePersonsByDistinctIds.mockResolvedValue([
            { teamId: 1, distinctId: 'anon-2', person: { ...person, id: '7' } },
        ] as never)
        await bound.flush()

        // The merge keeps the target's value on a shared key and takes the
        // source's only where it has none: that is $set_once, not $set.
        const redirected = repository.updatePersonProperties.mock.calls.at(-1)![0]
        expect(redirected.personId).toBe('7')
        expect(redirected.setProperties).toEqual({})
        expect(redirected.setOnceProperties).toEqual({ plan: 'stale' })
        expect(redirected.unsetProperties).toEqual([])
    })

    it('refreshes before concluding a person is gone', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        repository.updatePersonProperties
            .mockRejectedValueOnce(new NoRowsUpdatedError('merged away') as never)
            .mockResolvedValue({ person, updated: true } as never)
        // Identity lags the leader: the first answer still names the person
        // the leader has already lost, which must not read as a deletion.
        repository.resolvePersonsByDistinctIds
            .mockResolvedValueOnce([{ teamId: 1, distinctId: 'd1', person }] as never)
            .mockResolvedValue([{ teamId: 1, distinctId: 'd1', person: { ...person, id: '9' } }] as never)

        await bound.flush()

        expect(repository.updatePersonProperties).toHaveBeenLastCalledWith(
            expect.objectContaining({ personId: '9', setProperties: { a: '1' } }),
            expect.any(String)
        )
    })

    describe('carried operations', () => {
        const mergeRequest = () => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
            eventOps: ops({}, '$identify'),
            opId: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        const respondWith = (carriedApplied: string[]) => {
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied,
            })
        }

        it('sends a fenced person’s pending operations inside the merge request', async () => {
            const bound = store.forBatch(0)
            respondWith([])
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'paid' } }), 'anon-1')

            await bound.mergePersons(mergeRequest())

            // Asserted whole: a field dropped from the payload is lost
            // outright once the echo makes the store discard the segment,
            // so naming only some of them would hide exactly that.
            expect(repository.mergePersons.mock.calls[0][0].carriedOperations).toEqual([
                {
                    distinctId: 'anon-1',
                    set: { plan: 'paid' },
                    setOnce: {},
                    unset: [],
                    eventName: '$set',
                    isIdentified: undefined,
                    lastSeenAtMs: undefined,
                    expectedPersonId: '9',
                },
            ])
        })

        it.each([
            // The echo is the whole contract: a server that predates the
            // field, or a replay, names nothing and the operations must
            // still reach the leader the ordinary way.
            ['the service applied them', ['anon-1'], 0],
            ['the service named none', [], 1],
        ])('writes them afterwards when %s: %s more times', async (_label, carriedApplied, expectedWrites) => {
            const bound = store.forBatch(0)
            respondWith(carriedApplied as string[])
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'paid' } }), 'anon-1')
            await bound.mergePersons(mergeRequest())

            repository.updatePersonProperties.mockClear()
            await bound.flush()

            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(expectedWrites as number)
        })

        it('keeps a concurrent flush off the segments it carried', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'paid' } }), 'anon-1')
            // A flush that wrote the same segment would leave two
            // truncations racing over one entry, dropping whichever
            // segment arrived between them.
            let flushed: Promise<unknown> | undefined
            repository.mergePersons = jest.fn().mockImplementation(() => {
                flushed = bound.flush()
                return Promise.resolve({
                    survivor: person,
                    results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                    carriedApplied: ['anon-1'],
                })
            })

            await bound.mergePersons(mergeRequest())
            await flushed

            expect(repository.updatePersonProperties).not.toHaveBeenCalled()
        })
    })

    describe('round-5 closures', () => {
        it('a leading size rejection does not strand the snapshot tail past the ack', async () => {
            const bound = store.forBatch(0)
            // A pair-then-set_once composition forces two segments; the
            // leader rejects the first on size. The tail is a real write
            // from THIS batch: leaving it for "the next pass" leaves it for
            // a later batch, past this batch's ack — a crash then loses it.
            await bound.applyEventOps(person, ops({ $set: { big: 'x', k: 'a' }, $unset: ['k'] }), 'd1')
            await bound.applyEventOps(person, ops({ $set: { tail: 'kept' }, $set_once: { k: 'b' } }), 'd1')
            expect((store as any).entries.get('1:7').segments).toHaveLength(2)
            repository.updatePersonProperties
                .mockRejectedValueOnce(new PersonhogPropertiesSizeError('too big', 1, '7') as never)
                .mockResolvedValue({ person, updated: true } as never)

            await bound.flush()

            // The tail was written within the same flush, before the batch acks.
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(2)
            expect(repository.updatePersonProperties.mock.calls[1][0].setProperties).toEqual({ tail: 'kept' })
            expect((store as any).entries.get('1:7').segments).toHaveLength(0)
        })

        it('a size rejection mid-redirect still delivers the remainder to the survivor', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { big: 'x', k: 'a' }, $unset: ['k'] }), 'd1')
            await bound.applyEventOps(person, ops({ $set: { tail: 'kept' }, $set_once: { k: 'b' } }), 'd1')
            // The person is merged away; the redirect's first unit bounces on
            // size; the remainder must re-enter the redirect, not wait for a
            // later batch's flush.
            repository.updatePersonProperties.mockImplementation(((request: {
                personId: string
                setProperties?: Record<string, unknown>
                setOnceProperties?: Record<string, unknown>
            }) => {
                if (request.personId === '7') {
                    return Promise.reject(new NoRowsUpdatedError('merged away'))
                }
                if (request.setProperties?.big !== undefined || request.setOnceProperties?.big !== undefined) {
                    return Promise.reject(new PersonhogPropertiesSizeError('too big', 1, '9'))
                }
                return Promise.resolve({ person, updated: true })
            }) as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: { ...person, id: '9' } },
            ] as never)

            await bound.flush()

            const landed = repository.updatePersonProperties.mock.calls
                .map(([request]) => request)
                .filter((request) => request.personId === '9' && request.setProperties?.tail !== undefined)
            expect(landed).toHaveLength(1)
            expect((store as any).entries.get('1:7').segments).toHaveLength(0)
        })
    })

    describe('round-4 closures', () => {
        const mergeReq = (sources = ['anon-1']) => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: sources.map((distinctId) => ({ distinctId, eventUuid: 'event-uuid' })),
            eventOps: ops({}, '$identify'),
            opId: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('a fence releasing mid-round cannot make the flush ack over a deferred lane', async () => {
            const narrowStore = new PersonhogPersonsStore(repository, { maxConcurrentUpdates: 1 })
            const bound = narrowStore.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            // Three lanes, one slot: 8 holds the slot, 7 (the merge's
            // person) is queued behind it, 10 queued last. The sequence
            // forces the reviewer's window: 7 starts under the fence and
            // defers; the merge then resolves and releases its fence while
            // 10's RPC still holds the round open — so when the round's
            // scan runs, 7 is neither fenced nor in flight. A drain keyed
            // on "currently parked" acks over 7's unwritten ops.
            await bound.applyEventOps({ ...person, id: '8', uuid: 'u8' }, ops({ $set: { a: '1' } }), 'other-1')
            await bound.applyEventOps(person, ops({ $set: { plan: 'held' } }), 'd1')
            await bound.applyEventOps({ ...person, id: '10', uuid: 'u10' }, ops({ $set: { c: '3' } }), 'other-2')

            const releases = new Map<string, () => void>()
            const written: string[] = []
            repository.updatePersonProperties.mockImplementation(((request: { personId: string }) => {
                written.push(request.personId)
                if (request.personId === '8' || request.personId === '10') {
                    return new Promise((resolve) => {
                        releases.set(request.personId, () => resolve({ person, updated: true }))
                    })
                }
                return Promise.resolve({ person, updated: true })
            }) as never)
            let releaseMerge: () => void = () => {}
            repository.mergePersons = jest.fn().mockImplementation(
                () =>
                    new Promise((resolve) => {
                        releaseMerge = () => resolve({ survivor: person, results: [], carriedApplied: [] })
                    })
            )

            const flushing = bound.flush()
            await new Promise((resolve) => setTimeout(resolve, 0))
            // The merge fences person 7 while 8's write holds the slot, and
            // stays in flight.
            const merging = bound.mergePersons(mergeReq())
            await new Promise((resolve) => setTimeout(resolve, 0))
            // 8 lands; 7 starts under the live fence and defers; 10 takes
            // the slot.
            releases.get('8')?.()
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(written).toEqual(['8', '10'])
            // The merge resolves and releases its fence while 10 is still on
            // the wire — the exact window where 7 is invisible to a
            // parked-only scan.
            releaseMerge()
            await merging
            releases.get('10')?.()
            await flushing

            expect(written).toEqual(['8', '10', '7'])
            expect((narrowStore as any).entries.get('1:7')?.segments ?? []).toHaveLength(0)
        })

        it('a flush cannot resolve past a carried lane whose merge fails and hands the segments back', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            // A single-segment lane, so the merge carries it (marking it in
            // flight). The merge will FAIL and hand the segments back; a
            // flush that resolved while the carry held them would let the
            // batch ack over writes that come back afterwards.
            await bound.applyEventOps(person, ops({ $set: { plan: 'held' } }), 'd1')
            let failMerge: () => void = () => {}
            repository.mergePersons = jest.fn().mockImplementation(
                () =>
                    new Promise((_resolve, reject) => {
                        failMerge = () => reject(new Error('saga unreachable'))
                    })
            )
            const merging = bound.mergePersons(mergeReq()).catch((error: unknown) => error)
            await new Promise((resolve) => setTimeout(resolve, 0))

            let flushSettled = false
            const flushing = bound.flush().then(() => {
                flushSettled = true
            })
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(flushSettled).toBe(false)

            failMerge()
            await merging
            await flushing
            // The handed-back segments were written before the flush resolved.
            expect(repository.updatePersonProperties).toHaveBeenCalledWith(
                expect.objectContaining({ setProperties: { plan: 'held' } }),
                expect.any(String)
            )
            expect((store as any).entries.get('1:7').segments).toHaveLength(0)
        })

        it('a merge waits for a redirect already writing to its survivor', async () => {
            const bound = store.forBatch(0)
            // Lane 9's person was destroyed by an EXTERNAL merge (no local
            // reconcile, no demote marks); its redirect resolves survivor 7
            // and its RPC goes on the wire. A local merge then fences 7: it
            // must wait the redirect out, or the saga's newer writes land
            // first and the redirect's older raw $set overwrites them.
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'older' } }), 'anon-2')
            let releaseRedirect: () => void = () => {}
            const events: string[] = []
            repository.updatePersonProperties.mockImplementation(((request: { personId: string }) => {
                if (request.personId === '9') {
                    return Promise.reject(new NoRowsUpdatedError('merged away'))
                }
                return new Promise((resolve) => {
                    releaseRedirect = () => {
                        events.push('redirect-landed')
                        resolve({ person, updated: true })
                    }
                })
            }) as never)
            // Answered by requested id, so the merge's own fence resolve
            // maps d1 to person 7 — the survivor the redirect is writing to.
            repository.resolvePersonsByDistinctIds.mockImplementation(((keys: { distinctId: string }[]) =>
                Promise.resolve(
                    keys.map((key) => ({ teamId: 1, distinctId: key.distinctId, person: { ...person, id: '7' } }))
                )) as never)
            repository.mergePersons = jest.fn().mockImplementation(() => {
                events.push('merge-sent')
                return Promise.resolve({ survivor: person, results: [], carriedApplied: [] })
            })

            const flushing = bound.flush()
            await new Promise((resolve) => setTimeout(resolve, 0))
            const merging = bound.mergePersons(mergeReq())
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(events).toEqual([])

            releaseRedirect()
            await merging
            await flushing
            expect(events).toEqual(['redirect-landed', 'merge-sent'])
        })
    })

    describe('round-3 closures', () => {
        const mergeReq = (sources = ['anon-1']) => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: sources.map((distinctId) => ({ distinctId, eventUuid: 'event-uuid' })),
            eventOps: ops({}, '$identify'),
            opId: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('a queued write that starts under a fence defers instead of racing the merge', async () => {
            // One concurrency slot forces the second lane's write to start in
            // a later macrotask — after the merge fenced its person. The
            // capture-time fence check cannot see that future; only a check
            // at execution start can.
            const narrowStore = new PersonhogPersonsStore(repository, { maxConcurrentUpdates: 1 })
            const bound = narrowStore.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            await bound.applyEventOps({ ...person, id: '8', uuid: 'other' }, ops({ $set: { a: '1' } }), 'other-1')
            await bound.applyEventOps(person, ops({ $set: { plan: 'older' } }), 'd1')

            let releaseFirstWrite: () => void = () => {}
            const written: string[] = []
            repository.updatePersonProperties.mockImplementation(((request: { personId: string }) => {
                written.push(request.personId)
                if (written.length === 1) {
                    return new Promise((resolve) => {
                        releaseFirstWrite = () => resolve({ person, updated: true })
                    })
                }
                return Promise.resolve({ person, updated: true })
            }) as never)
            let releaseMerge: () => void = () => {}
            repository.mergePersons = jest.fn().mockImplementation(
                () =>
                    new Promise((resolve) => {
                        releaseMerge = () => resolve({ survivor: person, results: [], carriedApplied: [] })
                    })
            )

            const flushing = bound.flush()
            await new Promise((resolve) => setTimeout(resolve, 0))
            // Lane 8's write holds the only slot; person 7's lane is captured
            // but unstarted. The merge fences 7 now.
            const merging = bound.mergePersons(mergeReq())
            await new Promise((resolve) => setTimeout(resolve, 0))

            // Free the slot: 7's queued write begins under the fence and must
            // defer rather than send its unscrubbed segment mid-merge.
            releaseFirstWrite()
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(written).toEqual(['8'])

            releaseMerge()
            await merging
            await flushing
            // The drain wrote 7's lane after the merge settled.
            expect(written).toEqual(['8', '7'])
        })

        it('a fence appearing mid-redirect is waited out before the write', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'pre' } }), 'anon-2')
            repository.updatePersonProperties
                .mockRejectedValueOnce(new NoRowsUpdatedError('merged away') as never)
                .mockResolvedValue({ person, updated: true } as never)
            // The redirect's entry check sees no fence; a merge fences the
            // SURVIVOR while the resolve is in flight. Writing under it
            // would land pre-merge ops after the saga's own writes.
            let fenceRelease: (() => void) | undefined
            repository.resolvePersonsByDistinctIds.mockImplementation(() => {
                if (!fenceRelease) {
                    fenceRelease = (store as any).fencePersons(['1:7'])
                }
                return Promise.resolve([{ teamId: 1, distinctId: 'anon-2', person: { ...person, id: '7' } }]) as never
            })

            const flushing = bound.flush()
            await new Promise((resolve) => setTimeout(resolve, 0))
            // The redirect saw the survivor's fence and parked; nothing has
            // written to 7 yet.
            expect(
                repository.updatePersonProperties.mock.calls.filter(([request]) => request.personId === '7')
            ).toHaveLength(0)

            fenceRelease?.()
            await flushing
            expect(
                repository.updatePersonProperties.mock.calls.filter(([request]) => request.personId === '7')
            ).toHaveLength(1)
        })

        it('a stale finalizer cannot retire a recreated lane', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            const oldEntry = (store as any).entries.get('1:7')
            // The old entry drained and was replaced while an old write's
            // finalizer was still pending; retiring by key would take the
            // new lane's unwritten ops with it.
            ;(store as any).entries.delete('1:7')
            await bound.applyEventOps(person, ops({ $set: { b: '2' } }), 'd1')
            oldEntry.segments = []
            store.releaseBatch(0)
            ;(store as any).releaseWritten('1:7', oldEntry)

            expect((store as any).entries.get('1:7')?.segments).toHaveLength(1)
        })
    })

    describe('round-2 closures', () => {
        const mergeReq = (sources = ['anon-1']) => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: sources.map((distinctId) => ({ distinctId, eventUuid: 'event-uuid' })),
            eventOps: ops({}, '$identify'),
            opId: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('a merge waits for a write already on the wire before sending', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            await bound.applyEventOps(person, ops({ $set: { plan: 'older' } }), 'd1')

            // The lane's write is mid-RPC when the merge starts. If the merge
            // request goes out first, the saga applies its newer $set and
            // this older in-flight write lands on top of it — silently.
            let releaseWrite: () => void = () => {}
            repository.updatePersonProperties.mockImplementationOnce(
                (() =>
                    new Promise((resolve) => {
                        releaseWrite = () => resolve({ person, updated: true })
                    })) as never
            )
            const events: string[] = []
            repository.mergePersons = jest.fn().mockImplementation(() => {
                events.push('merge-sent')
                return Promise.resolve({ survivor: person, results: [], carriedApplied: [] })
            })

            const flushing = bound.flush()
            await new Promise((resolve) => setTimeout(resolve, 0))
            const merging = bound.mergePersons(mergeReq())
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(events).toEqual([])

            events.push('write-landed')
            releaseWrite()
            await merging
            await flushing

            expect(events).toEqual(['write-landed', 'merge-sent'])
        })

        it('a set_once-and-unset pair on an absent key keeps the value in the projection', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, properties: {} } as never)
            await bound.fetchForUpdate(1, 'd1')
            // The leader's unset removes only keys present before the op, so
            // a set_once pair on an absent key keeps the filled value.
            await bound.applyEventOps(person, ops({ $set_once: { pairKey: 'kept' }, $unset: ['pairKey'] }), 'd1')
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, properties: {} },
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })
            await bound.mergePersons(mergeReq())

            const projected = (store as any).memo.getProjection('1:7')
            expect(projected.properties.pairKey).toBe('kept')
        })
    })

    describe('convergence closures', () => {
        const mergeReq = (sources = ['anon-1']) => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: sources.map((distinctId) => ({ distinctId, eventUuid: 'event-uuid' })),
            eventOps: ops({}, '$identify'),
            opId: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('a flush does not resolve while a lane is parked behind a merge', async () => {
            personhogStoreFlushCounter.reset()
            const boundA = store.forBatch(0)
            const boundB = store.forBatch(1)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await boundA.fetchForUpdate(1, 'd1')
            // A multi-segment lane, so it cannot be carried: only the fence
            // parks it. Batch A folded these ops and will ack on flush.
            await boundA.applyEventOps(person, ops({ $set: { a: '1', k: 'x' }, $unset: ['k'] }), 'd1')
            await boundA.applyEventOps(person, ops({ $set: { b: '2' }, $set_once: { k: 'y' } }), 'd1')

            let releaseMerge: () => void = () => {}
            repository.mergePersons = jest.fn().mockImplementation(
                () =>
                    new Promise((resolve) => {
                        releaseMerge = () => resolve({ survivor: person, results: [], carriedApplied: [] })
                    })
            )
            const merging = boundB.mergePersons(mergeReq())
            await new Promise((resolve) => setTimeout(resolve, 0))

            // A flush that resolved here would let batch A ack while its ops
            // sit unwritten in the parked lane — a crash then loses acked
            // writes. The flush must wait the merge out and write first.
            let flushSettled = false
            const flushing = boundA.flush().then(() => {
                flushSettled = true
            })
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(flushSettled).toBe(false)
            expect(repository.updatePersonProperties).not.toHaveBeenCalled()
            const deferrals = (await personhogStoreFlushCounter.get()).values.filter(
                (value) => value.labels.outcome === 'deferred_fenced'
            )
            expect(deferrals.length).toBeGreaterThan(0)

            releaseMerge()
            await merging
            await flushing
            expect(repository.updatePersonProperties).toHaveBeenCalled()
            expect((store as any).entries.get('1:7').segments).toHaveLength(0)
        })

        it('a redirect waits out the person\u2019s fence before writing anywhere', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'pre' } }), 'anon-2')

            // The lane's write is captured BEFORE any fence exists; the merge
            // fences the person and reconciles while that write is on the
            // wire, then the write fails on the tombstone. Without the fence
            // wait, the redirect resolves mid-merge — before reconcile in the
            // general case — and writes pre-merge ops raw to the survivor.
            let fenceRelease: () => void = () => {}
            repository.updatePersonProperties.mockImplementationOnce((() => {
                fenceRelease = (store as any).fencePersons(['1:9'])
                ;(store as any).reconcileMergedPersons(
                    1,
                    [{ rank: 0, personKey: '1:9', distinctKey: '1:anon-2' }],
                    '1:7',
                    0
                )
                return Promise.reject(new NoRowsUpdatedError('merged away'))
            }) as never)
            repository.updatePersonProperties.mockResolvedValue({ person, updated: true } as never)
            let resolveCalls = 0
            let resolvedDuringFence = false
            repository.resolvePersonsByDistinctIds.mockImplementation(() => {
                resolveCalls += 1
                resolvedDuringFence = resolvedDuringFence || (store as any).fences.has('1:9')
                return Promise.resolve([{ teamId: 1, distinctId: 'anon-2', person: { ...person, id: '7' } }]) as never
            })

            const flushing = bound.flush()
            await new Promise((resolve) => setTimeout(resolve, 0))
            // The redirect is parked on the fence: no resolve has run yet.
            expect(resolveCalls).toBe(0)
            fenceRelease()
            await flushing

            expect(resolvedDuringFence).toBe(false)
            const redirected = repository.updatePersonProperties.mock.calls
                .map(([request]) => request)
                .filter((request) => request.personId === '7')
            expect(redirected[0].setOnceProperties).toEqual({ plan: 'pre' })
            expect(redirected[0].setProperties).toEqual({})
        })

        it('the create found branch reads the leader before its doc becomes a baseline', async () => {
            repository.getOrCreatePersonByDistinctId.mockResolvedValue({
                person: { ...person, properties: { plan: 'lagged' } },
                created: false,
            } as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, properties: { plan: 'leader' } } as never)
            const bound = store.forBatch(0)
            const result = await bound.createPerson(
                DateTime.fromMillis(3_600_000, { zone: 'utc' }),
                {},
                {},
                {},
                1,
                null,
                false,
                'advisory-uuid',
                { distinctId: 'd1' },
                undefined
            )

            // Identity's found-branch doc lags the leader; folding against it
            // can classify a genuinely new $set as no-change and suppress it.
            expect(repository.fetchPersonById).toHaveBeenCalledTimes(1)
            expect(result.success && result.person.properties).toEqual({ plan: 'leader' })
        })

        it('an awaited fetch crossing a merge installs nothing', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockImplementation(() => {
                // A merge reconciles while this resolve is in flight,
                // repointing the memo; the stale answer names the dead person.
                ;(store as any).reconcileMergedPersons(
                    1,
                    [{ rank: 0, personKey: '1:9', distinctKey: '1:anon-1' }],
                    '1:7',
                    0
                )
                return Promise.resolve([{ teamId: 1, distinctId: 'd2', person: { ...person, id: '9' } }]) as never
            })

            await bound.fetchForChecking(1, 'd2')

            expect((store as any).memo.resolutionOf('1:d2')).not.toBe('1:9')
        })

        it.each([
            ['rebase', true],
            ['demote', false],
        ])('a set-and-unset pair on an absent key keeps the value (%s)', async (_path, viaRebase) => {
            const bound = store.forBatch(0)
            if (viaRebase) {
                repository.resolvePersonsByDistinctIds.mockResolvedValue([
                    { teamId: 1, distinctId: 'd1', person },
                ] as never)
                repository.fetchPersonById.mockResolvedValue({ ...person, properties: {} } as never)
                await bound.fetchForUpdate(1, 'd1')
                // The pair key is absent on the survivor: the leader keeps
                // the set value (unset removes only pre-existing keys), so
                // the projection must too.
                await bound.applyEventOps(person, ops({ $set: { pairKey: 'kept' }, $unset: ['pairKey'] }), 'd1')
                repository.mergePersons = jest.fn().mockResolvedValue({
                    survivor: { ...person, properties: {} },
                    results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                    carriedApplied: [],
                })
                await bound.mergePersons(mergeReq())
                const projected = (store as any).memo.getProjection('1:7')
                expect(projected.properties.pairKey).toBe('kept')
            } else {
                await bound.applyEventOps(
                    { ...person, id: '9' },
                    ops({ $set: { pairKey: 'kept' }, $unset: ['pairKey'] }),
                    'anon-2'
                )
                const entry = (store as any).entries.get('1:9')
                entry.demoted = new Set(entry.segments)
                repository.updatePersonProperties
                    .mockRejectedValueOnce(new NoRowsUpdatedError('merged away') as never)
                    .mockResolvedValue({ person, updated: true } as never)
                repository.resolvePersonsByDistinctIds.mockResolvedValue([
                    { teamId: 1, distinctId: 'anon-2', person: { ...person, id: '7' } },
                ] as never)
                await bound.flush()
                const redirected = repository.updatePersonProperties.mock.calls
                    .map(([request]) => request)
                    .filter((request) => request.personId === '7')
                expect(redirected[0].setOnceProperties).toEqual({ pairKey: 'kept' })
            }
        })

        it('a deterministic INVALID_ARGUMENT is not wrapped as a call failure', async () => {
            const bound = store.forBatch(0)
            const rejection = new ConnectError('invalid', Code.InvalidArgument)
            repository.mergePersons = jest.fn().mockRejectedValue(rejection as never)

            // Wrapping it would fail the batch, and redelivery presents the
            // same request to the same validation forever — a permanently
            // wedged partition from one malformed id.
            const surfaced = await bound.mergePersons(mergeReq()).catch((error: unknown) => error)
            expect(surfaced).toBe(rejection)
        })
    })

    describe('verdict-pass closures', () => {
        const mergeReq = (sources = ['anon-1']) => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: sources.map((distinctId) => ({ distinctId, eventUuid: 'event-uuid' })),
            eventOps: ops({}, '$identify'),
            opId: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('a lane folded under a stale belief is still claimed by reconcile', async () => {
            const bound = store.forBatch(0)
            // The memo believes anon-1 names person 5 (a cross-pod remap has
            // since moved it); ops were folded for that person.
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '5' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '5' } as never)
            await bound.fetchForUpdate(1, 'anon-1')
            await bound.applyEventOps({ ...person, id: '5' }, ops({ $set: { plan: 'stale' } }), 'anon-1')
            // The merge's own resolve answers the current person, 9, and the
            // saga destroys 9 — overwriting the memo edge before reconcile
            // could read the old belief from it.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })

            await bound.mergePersons(mergeReq())

            // Without the captured belief, person 5's lane would never be
            // claimed and its pre-merge ops would redirect raw.
            expect((store as any).entries.get('1:5').demoted?.size).toBe(1)
        })

        it('a post-verdict processing bug surfaces as itself, not as a call failure', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })
            const bug = new Error('post-verdict bug')
            jest.spyOn(store as any, 'reconcileMergedPersons').mockImplementation(() => {
                throw bug
            })

            // Mislabeling this as a call failure would point responders at
            // the network and demote lanes for a merge that answered fine.
            const surfaced = await bound.mergePersons(mergeReq()).catch((error: unknown) => error)
            expect(surfaced).toBe(bug)
            expect(surfaced).not.toBeInstanceOf(PersonMergeCallFailedError)
        })

        it('a survivor-less verdict scrubs nothing from the target lane', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            await bound.applyEventOps(person, ops({ $set: { email: 'buffered', k: 'x' }, $unset: ['k'] }), 'd1')
            await bound.applyEventOps(person, ops({ $set: { other: 'kept' }, $set_once: { k: 'y' } }), 'd1')
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: null,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })

            await bound.mergePersons({
                ...mergeReq(),
                eventOps: ops({ $set: { email: 'new' } }, '$identify'),
            })

            // No survivor means no proof the event's writes landed anywhere;
            // scrubbing would delete buffered values nothing superseded.
            const lane = (store as any).entries.get('1:7')
            const remaining = lane.segments.flatMap((segment: any) => Object.keys(segment.set))
            expect(remaining).toContain('email')
        })
    })

    describe('residual closures', () => {
        const mergeReq = (sources = ['anon-1']) => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: sources.map((distinctId) => ({ distinctId, eventUuid: 'event-uuid' })),
            eventOps: ops({}, '$identify'),
            opId: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('fences a source person this pod never touched', async () => {
            const bound = store.forBatch(0)
            // The memo has never seen anon-1; only the merge's own resolve
            // can discover its person. Without that, a first-touch fold
            // landing mid-merge races the request and reconcile wrongly
            // demotes it.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            let releaseMerge: () => void = () => {}
            repository.mergePersons = jest.fn().mockImplementation(
                () =>
                    new Promise((resolve) => {
                        releaseMerge = () =>
                            resolve({
                                survivor: person,
                                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                                carriedApplied: [],
                            })
                    })
            )
            const merging = bound.mergePersons(mergeReq())
            await new Promise((resolve) => setTimeout(resolve, 0))

            let foldSettled = false
            const fold = bound
                .applyEventOps({ ...person, id: '9' }, ops({ $set: { raced: 'yes' } }), 'anon-2')
                .then(() => {
                    foldSettled = true
                })
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(foldSettled).toBe(false)

            releaseMerge()
            await merging
            await fold
            // The fold waited the merge out, so reconcile never saw it: its
            // lane is unmarked and writes as the post-merge write it is (raw,
            // via the redirect path) instead of being wrongly demoted.
            const lane = (store as any).entries.get('1:9')
            expect(lane.segments.at(-1).set).toEqual({ raced: 'yes' })
            expect(lane.demoted).toBeUndefined()
        })

        it('a prefetch response crossing a merge fills nothing', async () => {
            const boundPrefetch = store.forBatch(0)
            const bound = store.forBatch(1)
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '9' } as never)
            await bound.fetchForUpdate(1, 'anon-1')

            // The prefetch resolves anon-2 to the doomed person, and while
            // its leader read is in flight, a merge destroys that person and
            // rewrites the memo. The late fill must not reinstall the dead
            // person under anon-2. Answered by requested id, so the merge's
            // own fence resolve cannot leak anon-2's mapping into the memo.
            repository.resolvePersonsByDistinctIds.mockImplementation(((keys: { distinctId: string }[]) =>
                Promise.resolve(
                    keys
                        .filter((key) => key.distinctId === 'anon-2')
                        .map((key) => ({ teamId: 1, distinctId: key.distinctId, person: { ...person, id: '9' } }))
                )) as never)
            repository.fetchPersonById.mockImplementation(async () => {
                repository.mergePersons = jest.fn().mockResolvedValue({
                    survivor: person,
                    results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                    carriedApplied: [],
                })
                await bound.mergePersons(mergeReq())
                return { ...person, id: '9' } as never
            })
            await store.prefetchPersons([{ teamId: 1, distinctId: 'anon-2', batchId: 0 }])

            expect((store as any).memo.resolutionOf('1:anon-2')).not.toBe('1:9')
            void boundPrefetch
        })

        it('reasserts the merge event\u2019s $set_once behind a buffered $unset', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            // A pair-cut keeps the lane home, and the second segment unsets k.
            await bound.applyEventOps(person, ops({ $set: { a: '1', k: 'x' }, $unset: ['k'] }), 'd1')
            await bound.applyEventOps(person, ops({ $set: { b: '2' }, $unset: ['k'] }), 'd1')
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })

            await bound.mergePersons({
                ...mergeReq(),
                eventOps: ops({ $set_once: { k: 'z' } }, '$identify'),
            })

            // Sequential truth: unset k, then the event's $set_once fills z.
            // The saga's own attempt at merge time no-opped against the
            // present key, so the lane must deliver unset-then-fill in order.
            const lane = (store as any).entries.get('1:7')
            expect(lane.segments.at(-1).setOnce).toEqual({ k: 'z' })
            expect(lane.segments.some((segment: any) => segment.unset.includes('k'))).toBe(true)
        })

        it('a merge call failure fails the batch instead of acking', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockRejectedValue(new Error('transport closed') as never)

            await expect(bound.mergePersons(mergeReq())).rejects.toThrow(PersonMergeCallFailedError)
        })
    })

    describe('round-3 regressions', () => {
        it('a sibling id\u2019s checking read cannot degrade the update baseline', async () => {
            const bound = store.forBatch(0)
            // d1 read through the leader; the leader knows key k.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, properties: { k: 'leader' } } as never)
            await bound.fetchForUpdate(1, 'd1')

            // Another id of the same person read through checking: identity
            // lags the leader and does not know k yet. State is shared per
            // person, so a replace here would hand d1's next update read a
            // baseline without k — and an $unset k would then classify
            // no-change and be silently suppressed.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd2', person: { ...person, properties: {} } },
            ] as never)
            await bound.fetchForChecking(1, 'd2')

            const seen = await bound.fetchForUpdate(1, 'd1')
            expect(seen?.properties).toEqual({ k: 'leader' })
        })

        it('the read-your-write view reflects the scrub, not the pre-scrub replay', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            // A pair-cut keeps the target lane home (two segments).
            await bound.applyEventOps(person, ops({ $set: { email: 'old', k: 'x' }, $unset: ['k'] }), 'd1')
            await bound.applyEventOps(person, ops({ $set: { other: 'kept' }, $set_once: { k: 'y' } }), 'd1')
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, properties: { email: 'new' } },
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })

            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({ $set: { email: 'new' } }, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })

            // The scrub retracted the buffered email=old; a projection still
            // showing it would suppress a later legitimate $set email=old as
            // a no-change.
            const seen = await bound.fetchForUpdate(1, 'd1')
            expect(seen?.properties.email).toBe('new')
            expect(seen?.properties.other).toBe('kept')
        })

        it('a demoted net whose run ends on a denied event writes under a property-bearing name', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'pro' } }), 'anon-2')
            const entry = (store as any).entries.get('1:9')
            // A denied event folds only scalars; refusing property carriage
            // is the leader's denylist, keyed on the event name.
            const denied = ops({}, '$exception')
            denied.denied = true
            denied.lastSeenAtMs = 7_200_000
            entry.inFlight = true
            await bound.applyEventOps({ ...person, id: '9' }, denied, 'anon-2')
            entry.inFlight = false
            entry.demoted = new Set(entry.segments)

            repository.updatePersonProperties
                .mockRejectedValueOnce(new NoRowsUpdatedError('merged away') as never)
                .mockResolvedValue({ person, updated: true } as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-2', person: { ...person, id: '7' } },
            ] as never)
            await bound.flush()

            const redirected = repository.updatePersonProperties.mock.calls
                .map(([request]) => request)
                .filter((request) => request.personId === '7')
            expect(redirected).toHaveLength(1)
            expect(redirected[0].setOnceProperties).toEqual({ plan: 'pro' })
            expect(redirected[0].eventName).not.toBe('$exception')
            expect(redirected[0].lastSeenAtMs).toBe(7_200_000)
        })

        it('carries a lane whose id is over 400 UTF-16 units but within 400 code points', async () => {
            // The server counts characters (code points); a client filter
            // counting UTF-16 units would leave a legal lane behind.
            const astral = '\u{1F600}'.repeat(300) // 300 code points, 600 units
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: astral, outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { a: '1' } }), astral)

            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: astral, eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })

            expect(repository.mergePersons.mock.calls[0][0].carriedOperations).toHaveLength(1)
        })

        it('a caller mutating a fetched absent-person fallback cannot corrupt the memo', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'd1', person },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, properties: { plan: 'free' } } as never)
            await bound.fetchForUpdate(1, 'd1')
            // d2 maps to the person at checking grade, so the update read
            // re-resolves — and the stale response answers nothing. The
            // fallback serves the live mapping's state, which must be a
            // copy: this is the one fetch branch that returned the shared
            // memo object itself.
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'd2', person },
            ] as never)
            await bound.fetchForChecking(1, 'd2')
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([] as never)
            const fallback = await bound.fetchForUpdate(1, 'd2')
            expect(fallback).not.toBeNull()
            if (fallback) {
                fallback.properties.stamped = 'by-caller'
            }

            const seen = await bound.fetchForUpdate(1, 'd1')
            expect(seen?.properties.stamped).toBeUndefined()
        })

        it('derives a valid op uuid from a salted op id', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })
            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                opId: 'event-uuid#conflict1',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })

            // The salt lives in the derivation input; the wire always
            // carries a well-formed UUID the saga can parse.
            expect(repository.mergePersons.mock.calls[0][0].opId).toMatch(
                /^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$/
            )
        })
    })

    describe('round-2 coverage', () => {
        it('a fold proceeds past a fence whose merge never settles, counted as a timeout', async () => {
            jest.useFakeTimers()
            try {
                personhogStoreFenceCounter.reset()
                const bound = store.forBatch(0)
                repository.resolvePersonsByDistinctIds.mockResolvedValue([
                    { teamId: 1, distinctId: 'd1', person },
                ] as never)
                repository.fetchPersonById.mockResolvedValue({ ...person } as never)
                await bound.fetchForUpdate(1, 'd1')
                repository.mergePersons = jest.fn().mockImplementation(() => new Promise(() => {}))
                void bound.mergePersons({
                    teamId: 1,
                    targetDistinctId: 'd1',
                    sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                    eventOps: ops({}, '$identify'),
                    opId: 'event-uuid',
                    allowIdentifiedSources: false,
                    mergeMode: createDefaultSyncMergeMode(),
                    createdAtMs: 3_600_000,
                })
                // The fence installs after the merge's own resolve.
                await jest.advanceTimersByTimeAsync(0)

                let folded = false
                const fold = bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1').then(() => {
                    folded = true
                })
                // A hung merge must slow this person's folds, never stall the
                // partition: the bounded wait expires and the fold proceeds.
                await jest.advanceTimersByTimeAsync(6_000)
                await fold
                expect(folded).toBe(true)
                const waits = (await personhogStoreFenceCounter.get()).values
                expect(waits.map((wait) => wait.labels.outcome)).toEqual(['timeout'])
            } finally {
                jest.useRealTimers()
            }
        })

        it('the fence budget follows the merge rpc deadline it covers', async () => {
            // Sized from the deadline rather than fixed, so raising the RPC
            // timeout cannot leave folds abandoning fences the merge is
            // still legitimately using. A store given a 30s deadline must
            // still be waiting well past the 5s the default would allow.
            jest.useFakeTimers()
            try {
                const slowStore = new PersonhogPersonsStore(repository, { mergeRpcTimeoutMs: 30_000 })
                const bound = slowStore.forBatch(0)
                repository.resolvePersonsByDistinctIds.mockResolvedValue([
                    { teamId: 1, distinctId: 'd1', person },
                ] as never)
                repository.fetchPersonById.mockResolvedValue({ ...person } as never)
                await bound.fetchForUpdate(1, 'd1')
                repository.mergePersons = jest.fn().mockImplementation(() => new Promise(() => {}))
                void bound.mergePersons({
                    teamId: 1,
                    targetDistinctId: 'd1',
                    sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                    eventOps: ops({}, '$identify'),
                    opId: 'event-uuid',
                    allowIdentifiedSources: false,
                    mergeMode: createDefaultSyncMergeMode(),
                    createdAtMs: 3_600_000,
                })
                await jest.advanceTimersByTimeAsync(0)

                let folded = false
                const fold = bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1').then(() => {
                    folded = true
                })
                // Past the default budget, still parked behind the merge.
                await jest.advanceTimersByTimeAsync(6_000)
                expect(folded).toBe(false)

                // Past its own budget, the fold proceeds as usual.
                await jest.advanceTimersByTimeAsync(30_000)
                await fold
                expect(folded).toBe(true)
            } finally {
                jest.useRealTimers()
            }
        })

        it('demoted lanes reach the survivor in the merge\u2019s source order, not fold order', async () => {
            const bound = store.forBatch(0)
            // Folded in the OPPOSITE order of the merge's sources, so only
            // the rank sort can produce the right write order.
            await bound.applyEventOps({ ...person, id: '10' }, ops({ $set: { plan: 'second-source' } }), 'anon-2')
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'first-source' } }), 'anon-1')
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' },
                    { sourceDistinctId: 'anon-2', outcome: 'merged', sourcePersonId: '10' },
                ],
                carriedApplied: [],
            })
            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [
                    { distinctId: 'anon-1', eventUuid: 'event-uuid' },
                    { distinctId: 'anon-2', eventUuid: 'event-uuid' },
                ],
                eventOps: ops({}, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })

            repository.updatePersonProperties.mockImplementation(((request: { personId: string }) =>
                request.personId === '7'
                    ? Promise.resolve({ person, updated: true })
                    : Promise.reject(new NoRowsUpdatedError('merged away'))) as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person },
                { teamId: 1, distinctId: 'anon-2', person },
            ] as never)
            await bound.flush()

            // Earlier sources beat later ones, and a demoted lane lands as
            // first-wins $set_once — so anon-1's redirect must arrive first.
            const survivorWrites = repository.updatePersonProperties.mock.calls
                .map(([request]) => request)
                .filter((request) => request.personId === '7')
            expect(survivorWrites.map((request) => request.setOnceProperties)).toEqual([
                { plan: 'first-source' },
                { plan: 'second-source' },
            ])
        })

        it('a merged verdict with no survivor releases the dead ids to re-resolve', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValueOnce({ ...person, id: '9' } as never)
            await bound.fetchForUpdate(1, 'anon-1')
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: null,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })

            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })

            // With nowhere to repoint, the id must at least stop naming the
            // destroyed person.
            expect((store as any).memo.resolutionOf('1:anon-1') !== undefined).toBe(false)
            expect((store as any).memo.hasProjection('1:9')).toBe(false)
        })

        it('one batch releasing leaves a shared lane and its memos intact for the other', async () => {
            const boundA = store.forBatch(0)
            const boundB = store.forBatch(1)
            await boundA.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            await boundB.applyEventOps(person, ops({ $set: { b: '2' } }), 'd1')
            await boundA.flush()
            store.releaseBatch(0)

            // B still references the lane and the memo; more folds and a
            // final drain must work, then B's release frees everything.
            await boundB.applyEventOps(person, ops({ $set: { c: '3' } }), 'd1')
            await boundB.flush()
            store.releaseBatch(1)

            expect(store.getFlushStats()).toEqual({
                dirtyEntryCount: 0,
                referencedBatchCount: 0,
                cacheEntryCount: 0,
            })
        })
    })

    describe('round-2 regressions', () => {
        const mergeReq = (sources = ['anon-1']) => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: sources.map((distinctId) => ({ distinctId, eventUuid: 'event-uuid' })),
            eventOps: ops({}, '$identify'),
            opId: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('a late fill-only response does not roll back a drained lane\u2019s projection', async () => {
            // Batch 1 holds the projection alive by resolution reference
            // while batch 0 folds, flushes, and releases — retiring the
            // lane. The projection now has no lane behind it, which is
            // exactly when a stale install would slip past an entries-based
            // guard.
            const bound1 = store.forBatch(1)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound1.fetchForUpdate(1, 'd1')

            const bound0 = store.forBatch(0)
            await bound0.applyEventOps(person, ops({ $set: { flag: 'on' } }), 'd1')
            await bound0.flush()
            store.releaseBatch(0)
            expect((store as any).entries.has('1:7')).toBe(false)

            // A prefetch for another id of the same person, issued before
            // the flush, delivers its stale snapshot now. Installing it
            // would hand batch 1 a baseline without `flag`, and a
            // revert-shaped $set would then classify no-change and be
            // suppressed.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd2', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, properties: { plan: 'free' } } as never)
            await store.prefetchPersons([{ teamId: 1, distinctId: 'd2', batchId: 1 }])

            const seen = await bound1.fetchForUpdate(1, 'd1')
            expect(seen?.properties).toEqual(expect.objectContaining({ flag: 'on' }))
        })

        it('the update read class does not serve a checking-grade memo entry', async () => {
            const bound = store.forBatch(0)
            // Identity's embedded person lags the leader: the checking read
            // memoizes the lagged shape.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: { ...person, properties: { plan: 'lagged' } } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, properties: { plan: 'leader' } } as never)
            await bound.fetchForChecking(1, 'd1')

            const seen = await bound.fetchForUpdate(1, 'd1')

            // The update baseline must come from the leader, so the checking
            // hit is a miss for this class and the leader read runs.
            expect(repository.fetchPersonById).toHaveBeenCalledTimes(1)
            expect(seen?.properties).toEqual({ plan: 'leader' })
        })

        it('a mid-redirect fold survives even when the direct write landed segments first', async () => {
            const bound = store.forBatch(0)
            // Two segments; the first lands, the second hits the merged-away
            // person. The redirect then exhausts against a genuinely deleted
            // person while a new fold arrives — which this pass never
            // attempted and must not discard.
            await bound.applyEventOps(person, ops({ $set: { a: '1', k: 'x' }, $unset: ['k'] }), 'd1')
            await bound.applyEventOps(person, ops({ $set: { b: '2' }, $set_once: { k: 'y' } }), 'd1')
            repository.updatePersonProperties
                .mockResolvedValueOnce({ person, updated: true } as never)
                .mockRejectedValueOnce(new NoRowsUpdatedError('merged away') as never)
            let folded = false
            repository.resolvePersonsByDistinctIds.mockImplementation(async () => {
                if (!folded) {
                    folded = true
                    await bound.applyEventOps(person, ops({ $set: { later: 'fold' } }), 'd1')
                }
                return [] as never
            })

            await bound.flush()

            const entry = (store as any).entries.get('1:7')
            expect(entry.segments).toHaveLength(1)
            expect(entry.segments[0].set).toEqual({ later: 'fold' })
        })

        it('a fold onto a demote-marked segment starts a new segment instead of erasing the mark', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { pre: 'merge' } }), 'anon-2')
            const entry = (store as any).entries.get('1:9')
            entry.demoted = new Set(entry.segments)

            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { post: 'merge' } }), 'anon-2')

            // Folding in place replaces the object and the mark falls off;
            // the pre-merge ops would then redirect raw and beat survivor
            // values they lost. The post-merge op must land in its own,
            // unmarked segment.
            expect(entry.segments).toHaveLength(2)
            expect(entry.demoted.has(entry.segments[0])).toBe(true)
            expect(entry.demoted.has(entry.segments[1])).toBe(false)
        })

        it('a replayed merged verdict cannot mark the survivor dead through the memo', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })
            await bound.mergePersons(mergeReq())
            // The first call repointed anon-1 to the survivor. A replay of
            // the same verdict now resolves anon-1 to the survivor itself;
            // claiming that key dead would strip the survivor's projection
            // and mark its live lane for demotion.
            await bound.applyEventOps(person, ops({ $set: { alive: 'yes' } }), 'd1')
            await bound.mergePersons(mergeReq())

            const lane = (store as any).entries.get('1:7')
            expect(lane.demoted).toBeUndefined()
            expect((store as any).memo.resolutionOf('1:anon-1')).toBe('1:7')
        })

        it('a fold waits out a second merge fence installed behind the first', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')

            const releases: (() => void)[] = []
            repository.mergePersons = jest.fn().mockImplementation(
                () =>
                    new Promise((resolve) => {
                        releases.push(() => resolve({ survivor: person, results: [], carriedApplied: [] }))
                    })
            )
            const mergeA = bound.mergePersons(mergeReq(['anon-1']))
            // The fence installs after merge A's own resolve; wait for it.
            await new Promise((resolve) => setTimeout(resolve, 0))
            // The fold parks on merge A's fence…
            let fenceHeldWhenFoldLanded: boolean | undefined
            const fold = bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1').then(() => {
                fenceHeldWhenFoldLanded = (store as any).fences.has('1:7')
            })
            // …and merge B then installs its own fence over the same person.
            const mergeB = bound.mergePersons(mergeReq(['anon-2']))
            await new Promise((resolve) => setTimeout(resolve, 0))

            let foldSettled = false
            void fold.finally(() => {
                foldSettled = true
            })
            releases[0]()
            await mergeA
            // A macrotask boundary drains the fold's whole microtask chain,
            // so this observation cannot pass on scheduling depth: if the
            // fold were going to land off A's release alone, it has by now.
            await new Promise((resolve) => setTimeout(resolve, 0))
            // Merge A releasing proves only that A settled; B still holds
            // the person, so the fold must still be parked.
            expect(foldSettled).toBe(false)

            releases[1]()
            await mergeB
            await fold
            expect(fenceHeldWhenFoldLanded).toBe(false)
        })

        it('a successful redirect repoints the lane\u2019s distinct id at the survivor', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')

            // A merge on another pod destroyed the person; this store only
            // learns of it through the failed write.
            repository.updatePersonProperties
                .mockRejectedValueOnce(new NoRowsUpdatedError('merged away') as never)
                .mockResolvedValue({ person, updated: true } as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: { ...person, id: '12' } },
            ] as never)
            await bound.flush()

            // Without the repoint, every later event folds onto the dead
            // person and pays the redirect path forever.
            expect((store as any).memo.resolutionOf('1:d1')).toBe('1:12')
        })

        it('exhausting the refresh while identity still names the vanished person fails the flush', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            repository.updatePersonProperties.mockRejectedValue(new NoRowsUpdatedError('merged away') as never)
            // The lag shape: identity keeps answering the person the leader
            // lost. Dropping would lose the write whenever lag outruns the
            // budget, so the batch must fail and redeliver.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)

            await expect(bound.flush()).rejects.toThrow(/identity still resolves/)
            expect((store as any).entries.get('1:7').segments).toHaveLength(1)
        })

        it.each([
            ['a 500-code-point id', 'x'.repeat(150) + '\u{1F600}'.repeat(350)],
            ['a NUL-bearing id', 'anon\u0000one'],
        ])('never carries a lane under %s the service would reject', async (_label, distinctId) => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: distinctId, outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { a: '1' } }), distinctId)

            await bound.mergePersons({ ...mergeReq([distinctId]), targetDistinctId: 'd1' })

            expect(repository.mergePersons.mock.calls[0][0].carriedOperations).toEqual([])
        })

        it('does not memoize extra distinct ids when the person already existed', async () => {
            repository.getOrCreatePersonByDistinctId.mockResolvedValue({ person, created: false } as never)
            const bound = store.forBatch(0)
            await bound.createPerson(
                DateTime.fromMillis(3_600_000, { zone: 'utc' }),
                {},
                {},
                {},
                1,
                null,
                false,
                'advisory-uuid',
                { distinctId: 'd1' },
                [{ distinctId: 'd2' }]
            )

            // The service maps extras only on the creation branch; d2 may
            // belong to someone else entirely.
            expect((store as any).memo.resolutionOf('1:d2') !== undefined).toBe(false)
        })

        it('shutdown fails loudly while lanes still hold unwritten ops', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            await expect(store.shutdown()).rejects.toThrow(/unwritten ops/)
        })

        it('scrubs the merge event\u2019s $set keys from a target lane the carry left behind', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            // A pair-cut makes the target's lane two segments, which the
            // carry cannot express — the lane stays home.
            await bound.applyEventOps(person, ops({ $set: { email: 'old', k: 'x' }, $unset: ['k'] }), 'd1')
            await bound.applyEventOps(person, ops({ $set: { other: 'kept' }, $set_once: { k: 'y' } }), 'd1')
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })

            await bound.mergePersons({
                ...mergeReq(),
                eventOps: ops({ $set: { email: 'new' } }, '$identify'),
            })

            // The saga already applied email=new to the survivor; the older
            // buffered email must not write after it and win. Keys the event
            // never touched still write.
            const lane = (store as any).entries.get('1:7')
            const remaining = lane.segments.flatMap((segment: any) => Object.keys(segment.set))
            expect(remaining).not.toContain('email')
            expect(remaining).toContain('other')
        })
    })

    describe('review regressions', () => {
        it('carries every field the segment holds, so discarding it loses nothing', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: ['anon-1'],
            })
            const scalars = ops({ $set: { plan: 'paid' } })
            scalars.isIdentified = true
            scalars.lastSeenAtMs = 7_200_000
            await bound.applyEventOps({ ...person, id: '9' }, scalars, 'anon-1')

            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })

            // The echo makes the store drop the segment, so a field left off
            // the wire is lost outright rather than written later.
            expect(repository.mergePersons.mock.calls[0][0].carriedOperations?.[0]).toEqual(
                expect.objectContaining({ isIdentified: true, lastSeenAtMs: 7_200_000 })
            )
        })

        it('demotes a lane by its net effect, not segment by segment', async () => {
            const bound = store.forBatch(0)
            // A $set_once landing on a key left in the set-and-unset pair
            // state is the composition foldOps cannot represent, so the
            // second event starts a new segment. Across the two, `plan`
            // ends at 'second' and `k` at 'b'; $set_once is first-wins, so
            // demoting each segment alone would land 'first' and 'a'.
            await bound.applyEventOps(
                { ...person, id: '9' },
                ops({ $set: { plan: 'first', k: 'a' }, $unset: ['k'] }),
                'anon-2'
            )
            await bound.applyEventOps(
                { ...person, id: '9' },
                ops({ $set: { plan: 'second' }, $set_once: { k: 'b' } }),
                'anon-2'
            )
            const entry = (store as any).entries.get('1:9')
            expect(entry.segments.length).toBeGreaterThan(1)
            entry.demoted = new Set(entry.segments)

            repository.updatePersonProperties
                .mockRejectedValueOnce(new NoRowsUpdatedError('merged away') as never)
                .mockResolvedValue({ person, updated: true } as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-2', person: { ...person, id: '7' } },
            ] as never)
            await bound.flush()

            // One call, carrying the lane's net effect. Demoting segment by
            // segment would send two, and $set_once being first-wins would
            // leave the survivor on the superseded values.
            const redirected = repository.updatePersonProperties.mock.calls
                .map(([request]) => request)
                .filter((request) => request.personId === '7')
            expect(redirected).toHaveLength(1)
            // The net contributes only where the survivor lacks a key, and
            // under that condition the pair (set k then unset k in one
            // event) resolves to its set value — the leader's unset removes
            // only pre-existing keys — so the later $set_once never fills.
            expect(redirected[0].setOnceProperties).toEqual({ plan: 'second', k: 'a' })
            expect(redirected[0].setProperties).toEqual({})
            expect(redirected[0].unsetProperties).toEqual([])
        })

        it('keeps the segments a failed write never attempted', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1', k: 'x' }, $unset: ['k'] }), 'd1')
            await bound.applyEventOps(person, ops({ $set: { b: '2' }, $set_once: { k: 'y' } }), 'd1')
            const entry = (store as any).entries.get('1:7')
            expect(entry.segments.length).toBe(2)

            // The first segment lands; the second fails transiently. The
            // failure must not take the landed one's place in the lane, nor
            // discard anything it never sent.
            repository.updatePersonProperties
                .mockResolvedValueOnce({ person, updated: true } as never)
                .mockRejectedValueOnce(new Error('leader unavailable') as never)
            await expect(bound.flush()).rejects.toThrow('leader unavailable')

            expect(entry.segments).toHaveLength(1)
            expect(entry.segments[0].set).toEqual({ b: '2' })
        })

        it('folds onto the survivor when a fence releases, not the merged-away person', async () => {
            const bound = store.forBatch(0)
            const dead = { ...person, id: '9' }
            let releaseMerge: () => void = () => {}
            repository.mergePersons = jest.fn().mockImplementation(
                () =>
                    new Promise((resolve) => {
                        releaseMerge = () =>
                            resolve({
                                survivor: person,
                                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                                carriedApplied: [],
                            })
                    })
            )
            await bound.applyEventOps(dead, ops({ $set: { a: '1' } }), 'anon-1')

            const merging = bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })
            // The fence installs after the merge's own resolve; wait for it.
            await new Promise((resolve) => setTimeout(resolve, 0))
            // A caller holding the pre-merge person folds while the merge runs.
            const parked = bound.applyEventOps(dead, ops({ $set: { after: 'merge' } }), 'anon-1')
            releaseMerge()
            await merging
            await parked

            // The distinct id must still name the survivor, and the ops must
            // be on the survivor's lane rather than the destroyed person's.
            expect((store as any).memo.resolutionOf('1:anon-1')).toBe('1:7')
            expect((store as any).entries.get('1:7')?.segments.at(-1).set).toEqual({ after: 'merge' })
        })

        it('frees a person projection once its lane and its ids are gone', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            await bound.flush()
            expect(store.getFlushStats().cacheEntryCount).toBe(1)

            store.releaseBatch(0)

            // The lane drained and the last batch let go of the distinct id,
            // so nothing is left to keep the projection alive.
            expect(store.getFlushStats()).toEqual(expect.objectContaining({ dirtyEntryCount: 0, cacheEntryCount: 0 }))
        })

        it('shows later events the merged properties, with its own writes on top', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            // A pending local write on the target, so the projection exists
            // and recordFetch will refuse to overwrite it.
            await bound.applyEventOps(person, ops({ $set: { local: 'mine' } }), 'd1')

            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, properties: { plan: 'free', fromSource: 'merged' } },
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })
            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })

            // The merge folded `fromSource` in, which no local projection
            // could know; the batch's own unwritten `local` still stands.
            const seen = await bound.fetchForUpdate(1, 'd1')
            expect(seen?.properties).toEqual({ plan: 'free', fromSource: 'merged', local: 'mine' })
        })

        it('releases the lanes behind a demoted write that failed', async () => {
            const bound = store.forBatch(0)
            // Two lanes demoted by one merge. They write in rank order, one at
            // a time, so a throw on the first must not leave the second
            // marked in flight, which every later pass would skip forever.
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { a: '1' } }), 'anon-1')
            await bound.applyEventOps({ ...person, id: '10' }, ops({ $set: { b: '2' } }), 'anon-2')
            for (const id of ['9', '10']) {
                const entry = (store as any).entries.get(`1:${id}`)
                entry.demoted = new Set(entry.segments)
                entry.demoteRank = id === '9' ? 0 : 1
            }
            repository.updatePersonProperties.mockRejectedValue(new Error('leader unavailable') as never)

            await expect(bound.flush()).rejects.toThrow('leader unavailable')

            expect((store as any).entries.get('1:10').inFlight).toBe(false)
            // And the next pass can actually take them again.
            repository.updatePersonProperties.mockResolvedValue({ person, updated: true } as never)
            await bound.flush()
            const written = repository.updatePersonProperties.mock.calls.map(([request]) => request.personId)
            expect(written).toEqual(expect.arrayContaining(['9', '10']))
        })

        it('does not discard a segment folded while a redirect was running', async () => {
            const bound = store.forBatch(0)
            // Two segments, so the first can land and the second fail: the
            // snapshot count then overstates what is left, and re-reading it
            // after the redirect would sweep up anything folded meanwhile.
            await bound.applyEventOps(person, ops({ $set: { a: '1', k: 'x' }, $unset: ['k'] }), 'd1')
            await bound.applyEventOps(person, ops({ $set: { b: '2' }, $set_once: { k: 'y' } }), 'd1')
            expect((store as any).entries.get('1:7').segments).toHaveLength(2)

            repository.updatePersonProperties
                .mockResolvedValueOnce({ person, updated: true } as never)
                .mockRejectedValueOnce(new NoRowsUpdatedError('merged away') as never)
            // The person is gone for good, so the redirect exhausts its
            // re-resolves; a fold arriving meanwhile was never attempted by
            // this pass and must survive it.
            let foldedDuringRedirect = false
            repository.resolvePersonsByDistinctIds.mockImplementation(async () => {
                if (!foldedDuringRedirect) {
                    foldedDuringRedirect = true
                    await bound.applyEventOps(person, ops({ $set: { later: 'fold' } }), 'd1')
                }
                return [] as never
            })

            await bound.flush()

            const entry = (store as any).entries.get('1:7')
            expect(entry.segments).toHaveLength(1)
            expect(entry.segments[0].set).toEqual({ later: 'fold' })
        })

        it('demotes only the segments that predate the merge', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { before: 'merge' } }), 'anon-2')
            const entry = (store as any).entries.get('1:9')
            entry.demoted = new Set(entry.segments)
            // Folded after the merge decided the conflict, so this one is a
            // later write and keeps its own precedence.
            entry.inFlight = true
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { after: 'merge' } }), 'anon-2')
            entry.inFlight = false
            expect(entry.segments).toHaveLength(2)

            repository.updatePersonProperties
                .mockRejectedValueOnce(new NoRowsUpdatedError('merged away') as never)
                .mockResolvedValue({ person, updated: true } as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-2', person: { ...person, id: '7' } },
            ] as never)
            await bound.flush()

            const redirected = repository.updatePersonProperties.mock.calls
                .map(([request]) => request)
                .filter((request) => request.personId === '7')
            expect(redirected).toHaveLength(2)
            expect(redirected[0].setOnceProperties).toEqual({ before: 'merge' })
            expect(redirected[1].setProperties).toEqual({ after: 'merge' })
        })

        it('leaves behind a lane whose distinct id the service would reject', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: 'anonymous', outcome: 'merged', sourcePersonId: '9' }],
                carriedApplied: [],
            })
            // A lane's distinct id is whichever one folded first, so it is not
            // held to the merge's id rules. Carrying an illegal one would make
            // the service reject the whole request.
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { a: '1' } }), 'anonymous')

            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anonymous', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })

            expect(repository.mergePersons.mock.calls[0][0].carriedOperations).toEqual([])
            // Left in the lane, so it still writes the ordinary way.
            expect((store as any).entries.get('1:9').segments).toHaveLength(1)
        })

        it('marks lanes for demotion when the merge call itself fails', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { a: '1' } }), 'anon-1')
            repository.mergePersons = jest.fn().mockRejectedValue(new Error('deadline exceeded') as never)

            await expect(
                bound.mergePersons({
                    teamId: 1,
                    targetDistinctId: 'd1',
                    sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                    eventOps: ops({}, '$identify'),
                    opId: 'event-uuid',
                    allowIdentifiedSources: false,
                    mergeMode: createDefaultSyncMergeMode(),
                    createdAtMs: 3_600_000,
                })
            ).rejects.toThrow('deadline exceeded')

            // The saga is resumable, so the merge may have committed anyway;
            // an unmarked lane would overwrite what it decided.
            const marked = (store as any).entries.get('1:9')
            expect(marked.demoted.size).toBe(marked.segments.length)
        })
    })

    it('redirects through consecutive merges instead of dropping on the second', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        repository.updatePersonProperties
            .mockRejectedValueOnce(new NoRowsUpdatedError('merged away'))
            .mockRejectedValueOnce(new NoRowsUpdatedError('survivor merged away too'))
            .mockResolvedValue({ person: { ...person, id: '10', version: 4 }, updated: true } as never)
        repository.resolvePersonsByDistinctIds
            .mockResolvedValueOnce([{ teamId: 1, distinctId: 'd1', person: { ...person, id: '9' } }] as never)
            .mockResolvedValueOnce([{ teamId: 1, distinctId: 'd1', person: { ...person, id: '10' } }] as never)

        await bound.flush()

        expect(repository.updatePersonProperties).toHaveBeenLastCalledWith(
            expect.objectContaining({ personId: '10', setProperties: { a: '1' } }),
            expect.any(String)
        )
    })

    it('fails the flush rather than dropping ops a lineage keeps outrunning', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        repository.updatePersonProperties.mockRejectedValue(new NoRowsUpdatedError('merged away') as never)
        let nextId = 8
        repository.resolvePersonsByDistinctIds.mockImplementation(() =>
            Promise.resolve([{ teamId: 1, distinctId: 'd1', person: { ...person, id: String(nextId++) } }] as never)
        )

        // Throwing rather than dropping is the claim; the attempt budget is
        // a tuning constant and not what this pins.
        await expect(bound.flush()).rejects.toThrow(/merged away \d+ times during redirect/)
    })

    it('fails the flush on unexpected errors so the batch retries whole', async () => {
        repository.updatePersonProperties.mockRejectedValue(new Error('leader unreachable'))
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        await expect(bound.flush()).rejects.toThrow('leader unreachable')
    })

    describe('concurrent batches share one flush', () => {
        const personB: () => InternalPerson = () => ({ ...person, id: '8', uuid: 'person-uuid-8' })

        it("a sibling entry's failure leaves it in its lane for the next pass", async () => {
            const bound0 = store.forBatch(0)
            const bound1 = store.forBatch(1)
            await bound0.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            await bound1.applyEventOps(personB(), ops({ $set: { b: '2' } }), 'd2')

            repository.updatePersonProperties.mockImplementation((request) =>
                request.personId === '8'
                    ? Promise.reject(new Error('leader unreachable'))
                    : Promise.resolve({ person: { ...person, version: 2 }, updated: true })
            )
            await expect(store.flush()).rejects.toThrow('leader unreachable')

            repository.updatePersonProperties.mockClear()
            repository.updatePersonProperties.mockResolvedValue({ person: { ...person, version: 2 }, updated: true })
            await store.flush()
            // Only the failed entry survives to re-write; the succeeded
            // one was consumed by the first pass.
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
            expect(repository.updatePersonProperties.mock.calls[0][0].personId).toBe('8')
        })

        it('flush passes serialize, so ops folded mid-pass write strictly after it', async () => {
            let releaseFirst!: () => void
            const firstGate = new Promise<void>((resolve) => {
                releaseFirst = resolve
            })
            const callOrder: string[] = []
            repository.updatePersonProperties
                .mockImplementationOnce(async () => {
                    callOrder.push('first:start')
                    await firstGate
                    callOrder.push('first:end')
                    return { person: { ...person, version: 2 }, updated: true }
                })
                .mockImplementation(() => {
                    callOrder.push('second')
                    return Promise.resolve({ person: { ...person, version: 3 }, updated: true })
                })

            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            const firstFlush = store.flush()
            // Spin microtasks until the first pass is mid-write, blocked
            // on the gate, so the next fold genuinely lands mid-pass.
            for (let i = 0; i < 100 && !callOrder.includes('first:start'); i++) {
                await Promise.resolve()
            }
            await bound.applyEventOps(person, ops({ $set: { a: '2' } }), 'd1')
            const secondFlush = store.flush()
            releaseFirst()
            await Promise.all([firstFlush, secondFlush])

            expect(callOrder).toEqual(['first:start', 'first:end', 'second'])
        })

        it('two batches folding one person write once, and a filtered-only fold rides along', async () => {
            person.properties = { $browser: 'Firefox' }
            const bound0 = store.forBatch(0)
            const bound1 = store.forBatch(1)
            // One shared entry per person, so a filtered-only fold from one
            // batch and a real one from another are the same entry: it writes
            // once, and there is no second writer to race it.
            await bound0.applyEventOps(person, ops({ $set: { $browser: 'Chrome' } }, 'pageview'), 'd1')
            await bound1.applyEventOps(person, ops({ $set: { plan: 'pro' } }, 'pageview'), 'd1')
            await store.flush()
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
            expect(repository.updatePersonProperties.mock.calls[0][0].setProperties).toEqual({
                $browser: 'Chrome',
                plan: 'pro',
            })
        })
    })

    it('publishes nothing when the leader reports no change', async () => {
        repository.updatePersonProperties.mockResolvedValue({ person, updated: false })
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { plan: 'free' } }), 'd1')
        const results = await bound.flush()
        expect(results).toEqual([])
    })

    it('a later segment failing on a domain error does not undo earlier segments', async () => {
        const bound = store.forBatch(0)
        const pair = ops({ $set_once: { k: 'v' }, $unset: ['k'] })
        const cutter = ops({ $set_once: { k: 'later' } })
        await bound.applyEventOps(person, pair, 'd1')
        await bound.applyEventOps(person, cutter, 'd1')

        repository.updatePersonProperties
            .mockResolvedValueOnce({ person: { ...person, version: 2 }, updated: true })
            .mockRejectedValueOnce(new PersonhogPropertiesSizeError('too big', 1, '7'))
        const results = await bound.flush()
        // Both segments were written — the first landed before the second's
        // domain error, and the error skips rather than fails the flush.
        expect(repository.updatePersonProperties).toHaveBeenCalledTimes(2)
        expect(results).toEqual([])
    })

    it('pending state is visible through every distinct id of the person', async () => {
        const bound = store.forBatch(0)
        await bound.createPerson(
            DateTime.fromMillis(3_600_000, { zone: 'utc' }),
            {},
            {},
            {},
            1,
            null,
            false,
            'advisory-uuid',
            { distinctId: 'd1' },
            [{ distinctId: 'd2' }]
        )
        const viaD1 = await bound.fetchForUpdate(1, 'd1')
        await bound.applyEventOps(viaD1!, ops({ $set: { a: '1' } }), 'd1')

        const viaD2 = await bound.fetchForUpdate(1, 'd2')
        expect(viaD2?.properties).toMatchObject({ a: '1' })
        expect(repository.resolvePersonsByDistinctIds).not.toHaveBeenCalled()
    })

    it('pending ops are visible to later fetches and compose across events', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        const bound = store.forBatch(0)
        const fetched = await bound.fetchForUpdate(1, 'd1')
        await bound.applyEventOps(fetched!, ops({ $set: { a: '1' } }), 'd1')

        const refetched = await bound.fetchForUpdate(1, 'd1')
        expect(refetched?.properties).toEqual({ plan: 'free', a: '1' })
        expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(1)

        const [afterSecond] = await bound.applyEventOps(refetched!, ops({ $set: { b: '2' } }), 'd1')
        expect(afterSecond.properties).toEqual({ plan: 'free', a: '1', b: '2' })
    })

    it('releaseBatch frees the batch memo so later fetches hit the service again', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        const bound = store.forBatch(0)
        await bound.fetchForUpdate(1, 'd1')
        store.releaseBatch(0)
        await bound.fetchForUpdate(1, 'd1')
        expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(2)
    })

    it('releaseBatch defers eviction of an entry that still holds unwritten ops', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        store.releaseBatch(0)

        // Releasing must not discard writes the batch never got to write;
        // the entry survives its last reference until it drains.
        await store.flush()
        expect(repository.updatePersonProperties).toHaveBeenCalledWith(
            expect.objectContaining({ setProperties: { a: '1' } }),
            expect.any(String)
        )
    })

    it('releaseBatch evicts a drained entry once no batch references it', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        await store.flush()
        store.releaseBatch(0)
        expect(store.getFlushStats().dirtyEntryCount).toBe(0)
    })

    it('maps a direct diff update onto the folded RPC', async () => {
        const bound = store.forBatch(0)
        const [updated, messages] = await bound.updatePersonWithPropertiesDiffForUpdate(
            person,
            { plan: 'pro' },
            ['gone'],
            { is_identified: true, last_seen_at: DateTime.fromMillis(7_200_000, { zone: 'utc' }) },
            'd1'
        )
        const sent = repository.updatePersonProperties.mock.calls[0][0]
        expect(sent.setProperties).toEqual({ plan: 'pro' })
        expect(sent.unsetProperties).toEqual(['gone'])
        expect(sent.isIdentified).toBe(true)
        expect(sent.lastSeenAtMs).toBe(7_200_000)
        expect(updated).toEqual({ ...person, version: 2 })
        expect(messages).toEqual([])
    })

    it('refuses a diff update carrying fields the RPC cannot express', async () => {
        const bound = store.forBatch(0)
        await expect(
            bound.updatePersonWithPropertiesDiffForUpdate(person, {}, [], { created_at: person.created_at }, 'd1')
        ).rejects.toThrow(PersonhogPendingRpcError)
        expect(repository.updatePersonProperties).not.toHaveBeenCalled()
    })
})
