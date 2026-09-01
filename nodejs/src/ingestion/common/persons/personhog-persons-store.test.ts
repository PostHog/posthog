import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import { PersonhogFencedError, PersonhogPropertiesSizeError } from '~/common/personhog/persons'
import { PersonClaimedByLifecycleOpError } from '~/common/persons/repositories/person-repository'
import { NoRowsUpdatedError } from '~/common/utils/utils'
import { InternalPerson } from '~/types'

import { PersonMergeCallFailedError, createDefaultSyncMergeMode } from './person-merge-types'
import { extractEventOps } from './person-update'
import { mergeOpIdFromRequest } from './person-uuid'
import {
    PersonhogPersonsStore,
    PersonhogUnsupportedFieldError,
    derivedFenceWaitMs,
    personhogStoreFenceCounter,
    personhogStoreFlushCounter,
    personhogStoreShadowShedCounter,
} from './personhog-persons-store'

const counterTotal = async (counter: { get: () => Promise<{ values: { value: number }[] }> }): Promise<number> =>
    (await counter.get()).values.reduce((sum, entry) => sum + entry.value, 0)

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
            // The leader answers the person as of the write, which the store
            // installs as the projection. Answering the document unchanged
            // would model a leader that ignored the ops it was sent.
            updatePersonProperties: jest.fn().mockImplementation((request: any) => {
                const properties = { ...person.properties }
                for (const [key, value] of Object.entries(request.setOnceProperties ?? {})) {
                    if (!(key in properties)) {
                        properties[key] = value
                    }
                }
                Object.assign(properties, request.setProperties ?? {})
                for (const key of request.unsetProperties ?? []) {
                    delete properties[key]
                }
                return Promise.resolve({
                    person: {
                        ...person,
                        version: 2,
                        properties,
                        is_identified: request.isIdentified ? true : person.is_identified,
                        // The leader max-merges this rather than taking the
                        // request's value, so an out-of-order event cannot
                        // walk it backwards.
                        last_seen_at:
                            request.lastSeenAtMs &&
                            (!person.last_seen_at || request.lastSeenAtMs > person.last_seen_at.toMillis())
                                ? DateTime.fromMillis(request.lastSeenAtMs, { zone: 'utc' })
                                : person.last_seen_at,
                    },
                    updated: true,
                })
            }),
            getDistinctIdsForPersons: jest.fn().mockResolvedValue({}),
            getOrCreatePersonByDistinctId: jest.fn().mockResolvedValue({ person, created: true }),
        } as unknown as jest.Mocked<PersonHogPersonWriteRepository>
        store = new PersonhogPersonsStore(repository)
    })

    it.each([0, -1, 1.5])('refuses a max concurrent updates of %p at construction', (maxConcurrentUpdates) => {
        // pLimit throws on these, and it is built after lanes are claimed for
        // a write: the throw leaves them marked in flight with nothing left
        // to clear the mark, so every later pass defers them and the flush
        // exhausts its rounds. In shadow the whole thing is swallowed.
        expect(() => new PersonhogPersonsStore(repository, { maxConcurrentUpdates })).toThrow(
            'PERSONHOG_STORE_MAX_CONCURRENT_UPDATES must be an integer >= 1'
        )
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
            eventUuid: 'event-uuid',
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

    it('prefetch resolves a whole batch in one call instead of one per id', async () => {
        // The saving is the batching, not the caching: without a prefetch
        // each id resolves on its own. A single id cannot show the
        // difference, because one lazy resolve and one prefetched resolve
        // are both one call.
        const ids = ['d1', 'd2', 'd3']
        repository.resolvePersonsByDistinctIds.mockImplementation(((keys: { distinctId: string }[]) =>
            Promise.resolve(keys.map(({ distinctId }) => ({ teamId: 1, distinctId, person: { ...person } })))) as never)
        repository.fetchPersonById.mockResolvedValue({ ...person } as never)

        // Ordered as production does it: the prefetch step reaches the store
        // through the batch handle, so the batch exists before it fires.
        const bound = store.forBatch(0)
        await store.prefetchPersons(ids.map((distinctId) => ({ teamId: 1, distinctId, batchId: 0 })))
        for (const distinctId of ids) {
            expect((await bound.fetchForUpdate(1, distinctId))?.id).toBe('7')
        }

        expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(1)
        expect(repository.resolvePersonsByDistinctIds.mock.calls[0][0]).toHaveLength(ids.length)
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
            // Every merge that returns a survivor pays a leader refresh for
            // it; in this world the leader holds the folded document.
            repository.fetchPersonById.mockImplementation(((_teamId: number, personId: string) =>
                Promise.resolve(personId === '7' ? survivor() : { ...person, id: personId })) as never)
        })

        const mergeRequest = () => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
            eventOps: ops({ $set: { plan: 'pro' } }, '$identify'),
            eventUuid: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('an op-id-reused refusal settles raw and keeps the batch view', async () => {
            // The replay guard's refusal is deterministic, so wrapping it
            // would redeliver one duplicated event uuid into the same
            // refusal until the recorded op ages out — a wedged partition.
            // It refuses before any durable work, so the view stands too.
            repository.mergePersons = jest
                .fn()
                .mockRejectedValue(
                    new ConnectError(
                        'op_id was already used for a different request',
                        Code.FailedPrecondition,
                        new Headers({ 'x-semantic-refusal': 'op_id_reused' })
                    )
                )
            const bound = store.forBatch(0)
            await bound.fetchForUpdate(1, 'd1')
            const error = await bound.mergePersons(mergeRequest()).catch((e) => e)
            expect(error).toBeInstanceOf(ConnectError)
            expect(error).not.toBeInstanceOf(PersonMergeCallFailedError)
            expect((store as any).memo.resolutionOf('1:d1')).toBeDefined()
        })

        it('any other failed call invalidates the team view and fails the batch', async () => {
            // A semantic refusal from a later saga step arrives after
            // sources may have been sealed or flipped, and a transport
            // failure's progress is unknowable; both must invalidate.
            const refuse = (code: Code, metadata?: Headers) => {
                repository.mergePersons = jest
                    .fn()
                    .mockRejectedValue(new ConnectError('refused after the flip', code, metadata))
            }

            refuse(Code.FailedPrecondition, new Headers({ 'x-semantic-refusal': 'release-unverified' }))
            let bound = store.forBatch(0)
            await bound.fetchForUpdate(1, 'd1')
            await expect(bound.mergePersons(mergeRequest())).rejects.toBeInstanceOf(PersonMergeCallFailedError)
            expect((store as any).memo.resolutionOf('1:d1')).toBeUndefined()

            refuse(Code.Unavailable)
            bound = store.forBatch(1)
            await bound.fetchForUpdate(1, 'd1')
            await expect(bound.mergePersons(mergeRequest())).rejects.toBeInstanceOf(PersonMergeCallFailedError)
            expect((store as any).memo.resolutionOf('1:d1')).toBeUndefined()
        })

        it('derives one op id per delivery regardless of how the event payload drifts', async () => {
            // Two deliveries of one event disagree on properties later stages
            // refresh, but must present the same op id so the second attaches
            // to what the first recorded.
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: survivor(),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
            })
            const bound = store.forBatch(0)

            await bound.mergePersons(mergeRequest())
            await bound.mergePersons({
                ...mergeRequest(),
                eventOps: ops({ $set: { $geoip_city_name: 'Berlin' } }, '$identify'),
                createdAtMs: 9_999_999,
            })

            const opIds = (repository.mergePersons as jest.Mock).mock.calls.map(([call]) => call.opId)
            expect(opIds).toHaveLength(2)
            expect(opIds[1]).toBe(opIds[0])
        })

        it('floors a pre-epoch created_at, which the saga refuses', async () => {
            // The Postgres backend stores the raw value, so the floor lives
            // here rather than in the shared request both backends read.
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, id: '7' },
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
            })
            const bound = store.forBatch(0)

            await bound.mergePersons({ ...mergeRequest(), createdAtMs: -86_400_000 })

            expect((repository.mergePersons as jest.Mock).mock.calls[0][0].createdAtMs).toBe(0)
        })

        it('a conflict gets the full salted retry budget before surfacing as the claim error', async () => {
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: null,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'skipped_conflict' }],
            })
            const bound = store.forBatch(0)

            await expect(bound.mergePersons(mergeRequest())).rejects.toBeInstanceOf(PersonClaimedByLifecycleOpError)

            // An aborted conflict is recorded terminally and replays under
            // its op id, so each retry salts a fresh identity. Safe because a
            // conflict verdict proves nothing was destroyed.
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
                eventUuid: 'event-uuid',
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
                eventUuid: 'event-uuid',
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
                eventUuid: 'event-uuid',
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
                eventUuid: 'event-uuid',
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
                    eventUuid: 'event-uuid',
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
            const bound = store.forBatch(0)
            await bound.fetchForUpdate(1, 'anon-2')

            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                eventUuid: 'event-uuid',
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
                eventUuid: 'event-uuid',
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
            repository.fetchPersonById.mockResolvedValue(survivor() as never)
            const seen = await bound.fetchForUpdate(1, 'anon-1-alias')
            expect(seen?.id).toBe('7')
            expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(1)
        })
    })

    it('creation memoizes the primary id and leaves the extras to resolve', async () => {
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
        expect(repository.resolvePersonsByDistinctIds).not.toHaveBeenCalled()

        // The created flag speaks only for the primary: the service leaves
        // a live conflicting extra mapped to its existing person, so an
        // edge memoized here could name a person the service never mapped
        // d2 to. The extra pays one resolve on first touch instead.
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd2', person }] as never)
        await bound.fetchForUpdate(1, 'd2')
        expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(1)
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

    describe('round-6 closures', () => {
        const mergeReq = (sources = ['anon-1', 'anon-2']) => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: sources.map((distinctId) => ({ distinctId, eventUuid: 'event-uuid' })),
            eventOps: ops({}, '$identify'),
            eventUuid: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('an aborted row recorded in the error vocabulary still aborts the fold', async () => {
            // Completion implies at least one merged source, so an
            // error-without-merged row can only be an abort; executing it
            // would misattribute the run.
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, id: '7' },
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'error' },
                    { sourceDistinctId: 'anon-2', outcome: 'error' },
                ],
            })

            const result = await bound.mergePersons(mergeReq())

            expect(result.foldAborted).toBe('error')
            expect(result.survivor).toBeNull()
        })

        it('an aborted fold still floors the survivor at the version its response proved', async () => {
            const bound = store.forBatch(0)
            ;(store as any).memo.offerBaseline('1:7', { ...person, version: 3 }, 'leader-read')
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, version: 9 },
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' },
                    { sourceDistinctId: 'anon-2', outcome: 'skipped_conflict' },
                ],
            })

            await bound.mergePersons(mergeReq())

            // The saga's partial folds and the aborted-writes delivery moved
            // the leader past the standing baseline despite the abort.
            expect((store as any).memo.hasBaseline('1:7')).toBe(false)
            ;(store as any).memo.offerBaseline('1:7', { ...person, version: 8 }, 'leader-read')
            expect((store as any).memo.hasBaseline('1:7')).toBe(false)
        })

        it('a refresh answered under a team invalidation installs nothing', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, version: 5 },
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
            })
            repository.fetchPersonById.mockImplementation((() => {
                // A concurrent merge fails without a verdict while this read
                // is on the wire; which persons died is unknowable, and
                // every other read declines through the epoch it takes.
                ;(store as any).memo.invalidateTeam(1)
                return Promise.resolve({ ...person, version: 6 })
            }) as never)

            const result = await bound.mergePersons(mergeReq(['anon-1']))

            // The caller still gets the read; the memo must not.
            expect(result.survivor?.version).toBe(6)
            expect((store as any).memo.lookup(1, 'd1', 'update')).toBeUndefined()
        })

        it('a refresh answered below the merge keeps the newer response survivor', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, version: 5, properties: { plan: 'folded' } },
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
            })
            // A deposed leader inside its detection window can answer below
            // the merge's own commit; a fold plan would serve that older
            // document to every later event in its run.
            repository.fetchPersonById.mockResolvedValue({
                ...person,
                version: 4,
                properties: { plan: 'old' },
            } as never)

            const result = await bound.mergePersons(mergeReq(['anon-1']))

            expect(result.survivor).toMatchObject({ version: 5, properties: { plan: 'folded' } })
        })

        it('an update read below a standing floor re-reads instead of serving the stale document', async () => {
            // The memo refuses the install either way; the defect this pins
            // is the returned copy, which the fold would otherwise classify
            // ops against and suppress a genuine change as no-change.
            const bound = store.forBatch(0)
            ;(store as any).memo.dropBaseline('1:7', 5)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById
                .mockResolvedValueOnce({ ...person, version: 3, properties: { plan: 'stale' } } as never)
                .mockResolvedValue({ ...person, version: 5, properties: { plan: 'current' } } as never)

            const seen = await bound.fetchForUpdate(1, 'd1')

            expect(seen).toMatchObject({ version: 5, properties: { plan: 'current' } })
        })

        it('an update read that keeps arriving below the floor fails the batch', async () => {
            const bound = store.forBatch(0)
            ;(store as any).memo.dropBaseline('1:7', 5)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, version: 3 } as never)

            await expect(bound.fetchForUpdate(1, 'd1')).rejects.toThrow('below the version floor')
        })

        it('a successful redirect stamps the id and the dead person like every removal', async () => {
            // Without the bump, a read of this id already on the wire passes
            // its moved check and reinstalls the dead edge the repoint just
            // healed; without the mark, a read answering the dead person
            // refills its baseline.
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            repository.updatePersonProperties.mockImplementationOnce((() =>
                Promise.reject(new NoRowsUpdatedError('merged away'))) as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: { ...person, id: '9' } },
            ] as never)

            await bound.flush()

            const memo = (store as any).memo
            expect(memo.resolutionOf('1:d1')).toBe('1:9')
            expect(memo.versionOf('1:d1')).toBeGreaterThan(0)
            expect(memo.isDestroyed('1:7')).toBe(true)
        })

        it('an anchorless direct diff with an applied null answer floors at the caller document', async () => {
            // No memo view stands, but the caller's document is a sound
            // anchor: the leader held its version at the read, and the
            // applied write moved past it.
            const bound = store.forBatch(0)
            repository.updatePersonProperties.mockResolvedValueOnce({ person: null, updated: true } as never)

            await bound.updatePersonWithPropertiesDiffForUpdate(person, { plan: 'pro' }, [], {}, 'd1')

            const memo = (store as any).memo
            memo.offerBaseline('1:7', { ...person, version: 1 }, 'leader-read')
            expect(memo.hasBaseline('1:7')).toBe(false)
            memo.offerBaseline('1:7', { ...person, version: 2 }, 'leader-read')
            expect(memo.hasBaseline('1:7')).toBe(true)
        })

        it('a direct diff answered with no document but an applied write floors the view', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            repository.updatePersonProperties.mockResolvedValueOnce({ person: null, updated: true } as never)

            await bound.updatePersonWithPropertiesDiffForUpdate(person, { plan: 'pro' }, [], {}, 'd1')

            // The write applied, so the pre-write baseline must not go on
            // serving, and a read carrying it back must be refused.
            expect((store as any).memo.hasBaseline('1:7')).toBe(false)
            ;(store as any).memo.offerBaseline('1:7', { ...person, version: 1 }, 'leader-read')
            expect((store as any).memo.hasBaseline('1:7')).toBe(false)
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
            eventUuid: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('a drained lane stops serving the update class', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: 1 } }), 'd1')
            // The write answers without a document, so the drain leaves no
            // leader-backed state behind.
            repository.updatePersonProperties.mockResolvedValue({ person: null } as never)
            await bound.flush()
            // The entry outlives its segments while the batch still holds it.
            expect((store as any).entries.get('1:7').segments).toHaveLength(0)

            // A checking read refills the baseline from identity, which lags.
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'd1', person: { ...person, version: 2, properties: { plan: 'lagged' } } },
            ] as never)
            await bound.fetchForChecking(1, 'd1')

            // With the lane drained, nothing entitles that identity document
            // to serve the update class, so the read has to reach the leader.
            const fresher = { ...person, version: 9, properties: { plan: 'enterprise' } }
            repository.fetchPersonById.mockResolvedValue(fresher as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: fresher },
            ] as never)

            const seen = await bound.fetchForUpdate(1, 'd1')
            expect(seen?.version).toBe(9)
            expect(repository.fetchPersonById).toHaveBeenCalled()
        })

        it("a create that finds an existing person serves the leader's document, not identity's", async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { fromBatch: 'yes' } }), 'd1')
            await bound.flush()
            // The lane drained but the entry survives while the batch holds
            // it, so nothing unwritten is left to protect.
            expect((store as any).entries.get('1:7').segments).toHaveLength(0)

            // A second id lands on the same person. Identity answers a
            // document that predates this batch's flushed write; the
            // branch's leader read answers the truth, which contains it.
            repository.getOrCreatePersonByDistinctId.mockResolvedValue({
                person: { ...person, properties: { plan: 'free' } },
                created: false,
            } as never)
            repository.fetchPersonById.mockResolvedValue({
                ...person,
                version: 2,
                properties: { plan: 'free', fromBatch: 'yes' },
            } as never)

            await bound.createPerson(
                DateTime.fromMillis(3_600_000, { zone: 'utc' }),
                {},
                {},
                {},
                1,
                null,
                false,
                'advisory-uuid',
                { distinctId: 'd2' }
            )

            // Installing identity's lagging document instead would roll the
            // batch's own flushed write out of its view.
            expect((store as any).memo.snapshot((store as any).memo.lookup(1, 'd1', 'checking'))).toMatchObject({
                properties: { plan: 'free', fromBatch: 'yes' },
            })
        })

        it('a write leaves the projection naming the leader, not the last read', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { fromBatch: 'yes' } }), 'd1')
            // The projection still carries the version of the read it was
            // built from until the write answers.
            expect((store as any).memo.snapshot((store as any).memo.lookup(1, 'd1', 'checking')).version).toBe(1)

            await bound.flush()

            // Now it names what the leader answered. A read issued before
            // this write and delivered after it is older, and the version is
            // the only thing that says so.
            expect((store as any).memo.snapshot((store as any).memo.lookup(1, 'd1', 'checking'))).toMatchObject({
                version: 2,
                properties: { plan: 'free', fromBatch: 'yes' },
            })
        })

        it('the staler of two leader reads does not replace the newer', async () => {
            const bound = store.forBatch(0)
            // A read lands and installs the person at version 5.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: { ...person, version: 5, properties: { plan: 'pro' } } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({
                ...person,
                version: 5,
                properties: { plan: 'pro' },
            } as never)
            await bound.fetchForUpdate(1, 'd1')

            // A second read of the same person, issued earlier and delivered
            // now, answers the document as it stood before. Both came from
            // the leader, so only the version tells them apart.
            repository.getOrCreatePersonByDistinctId.mockResolvedValue({
                person: { ...person, version: 3, properties: { plan: 'free' } },
                created: false,
            } as never)
            repository.fetchPersonById.mockResolvedValue({
                ...person,
                version: 3,
                properties: { plan: 'free' },
            } as never)

            await bound.createPerson(
                DateTime.fromMillis(3_600_000, { zone: 'utc' }),
                {},
                {},
                {},
                1,
                null,
                false,
                'advisory-uuid',
                { distinctId: 'd2' }
            )

            expect((store as any).memo.snapshot((store as any).memo.lookup(1, 'd1', 'checking'))).toMatchObject({
                version: 5,
                properties: { plan: 'pro' },
            })
        })

        it('a direct diff update leaves the projection naming the leader', async () => {
            const bound = store.forBatch(0)
            await bound.updatePersonWithPropertiesDiffForUpdate(person, { plan: 'pro' }, [], {}, 'd1')

            // Installing the person it was handed instead of the one the
            // leader answered is the failure this names, and asserting only
            // that some projection exists would not see it.
            expect((store as any).memo.snapshot((store as any).memo.viewOfPerson('1:7'))).toMatchObject({
                version: 2,
                properties: { plan: 'pro' },
            })
        })

        it("rebuilding over a leader answer replays a pending segment's scalars", () => {
            // Tested where the rule lives: a segment still unsent carries an
            // identified flag the leader's answer cannot know about, and
            // rebuilding from properties alone would report the person
            // unidentified after this batch already decided otherwise.
            const pending = ops({ $set: { later: 'op' } }, '$identify')
            pending.isIdentified = true

            const rebuilt = (store as any).projectOver({ ...person, is_identified: false }, [pending])

            expect(rebuilt.is_identified).toBe(true)
            expect(rebuilt.properties).toMatchObject({ later: 'op' })
        })

        it('a write whose response carries no document drops the projection it outran', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { k: 'A' } }), 'd1')
            expect((store as any).memo.hasBaseline('1:7')).toBe(true)
            repository.updatePersonProperties.mockResolvedValueOnce({ person: null, updated: true } as never)

            await bound.flush()

            // The write landed, so the leader moved past the version the
            // projection holds. A read issued before it carries that same
            // version and would pass the replace guard, putting pre-write
            // state back as the batch's baseline.
            expect((store as any).memo.hasBaseline('1:7')).toBe(false)
        })

        it('a redirect that finds nobody sends the id back to identity', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { k: 'A' } }), 'd1')
            expect((store as any).memo.resolutionOf('1:d1')).toBe('1:7')
            // The person is deleted rather than merged, so the redirect's
            // resolve answers nobody and the ops have nowhere to land.
            repository.updatePersonProperties.mockRejectedValue(new NoRowsUpdatedError('deleted') as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([] as never)

            await bound.flush()

            // Keeping either would make every later event on this id fold
            // onto the deleted person and pay the whole redirect again.
            expect((store as any).memo.resolutionOf('1:d1')).toBeUndefined()
            expect((store as any).memo.hasBaseline('1:7')).toBe(false)
        })

        it.each([
            ['its resolve', 'resolve' as const],
            ['its person read', 'fetch' as const],
        ])('a prefetch released during %s records nothing', async (_case, window) => {
            store.forBatch(0)
            let release: () => void = () => {}
            const deferred = <T>(value: T): Promise<T> =>
                new Promise((resolve) => {
                    release = () => resolve(value)
                })
            if (window === 'resolve') {
                repository.resolvePersonsByDistinctIds.mockImplementation((() =>
                    deferred([{ teamId: 1, distinctId: 'd9', person }])) as never)
                repository.fetchPersonById.mockResolvedValue(person as never)
            } else {
                repository.resolvePersonsByDistinctIds.mockResolvedValue([
                    { teamId: 1, distinctId: 'd9', person },
                ] as never)
                repository.fetchPersonById.mockImplementation((() => deferred(person)) as never)
            }

            const prefetching = store.prefetchPersons([{ teamId: 1, distinctId: 'd9', batchId: 0 }])
            await new Promise((resolve) => setImmediate(resolve))
            // Released while that call is still out. Both windows need their
            // own check: a guard before the first await does not cover a
            // release that happens during the second.
            store.releaseBatch(0)
            release()
            await prefetching

            // Recording for a batch that has gone recreates its key set, and
            // every later release then reads the key as held elsewhere, so
            // nothing frees it again.
            expect((store as any).memo.resolutionOf('1:d9')).toBeUndefined()
            expect((store as any).memo.baselineCount).toBe(0)
        })

        it('does not install a created person a merge destroyed mid-call', async () => {
            const bound = store.forBatch(0)
            repository.getOrCreatePersonByDistinctId = jest.fn().mockImplementation((() => {
                // The merge names a different id entirely, so only the
                // person it destroyed connects it to this call.
                ;(store as any).reconcileMergedPersons(1, [{ personKey: '1:7', distinctKey: '1:elsewhere' }], '1:11', 0)
                return Promise.resolve({ success: true, person, created: true })
            }) as never)

            await bound.createPerson(DateTime.now(), {}, {}, {}, 1, null, false, 'advisory-uuid', { distinctId: 'd1' })

            // Installing it would put a destroyed person back as the batch's
            // baseline, and no id in this call was named by the merge.
            expect((store as any).memo.hasBaseline('1:7')).toBe(false)
        })

        const memoOf = (): any => (store as any).memo

        it('a merge verdict replayed after its survivor died cannot resurrect it', () => {
            const memo = (store as any).memo
            // Merge B destroyed person 9 — the survivor merge A's stale,
            // retried verdict still names.
            ;(store as any).reconcileMergedPersons(1, [{ personKey: '1:9', distinctKey: '1:b-src' }], '1:11', 0)

            // Merge A's replay lands afterwards, offering the destroyed
            // person through both install doors the memo has.
            memo.record(1, 'd1', { ...person, id: '9' }, 0, { readClass: 'update' })
            memo.offerBaseline('1:9', { ...person, id: '9' }, 'own-write')

            // Installing either would make a destroyed person the batch's
            // live, leader-backed answer for every later event on d1.
            expect(memo.resolutionOf('1:d1')).not.toBe('1:9')
            expect(memo.hasBaseline('1:9')).toBe(false)
        })

        it('a caller-held destroyed person cannot re-enter through fold seeding', async () => {
            const bound = store.forBatch(0)
            ;(store as any).reconcileMergedPersons(1, [{ personKey: '1:7', distinctKey: '1:elsewhere' }], '1:11', 0)

            // The caller still holds person 7 from before the merge and folds
            // onto a sibling id the memo has never seen, so personNow falls
            // back to the caller's copy and the fold seeds a baseline for it.
            await bound.applyEventOps(person, ops({ $set: { late: 'op' } }), 'd-sibling')

            // The ops themselves stay in the lane and the redirect will carry
            // them; what must not happen is the destroyed person becoming the
            // batch's readable baseline again.
            expect(memoOf().hasBaseline('1:7')).toBe(false)
        })

        it('a moved diff update floors its drop at the version the leader answered', async () => {
            const bound = store.forBatch(0)
            // A merge speaks for d1 while the write is on the wire, so the
            // answer cannot be installed and the baseline is dropped.
            repository.updatePersonProperties.mockImplementation((() => {
                memoOf().bumpId('1:d1')
                return Promise.resolve({ person: { ...person, version: 5 }, updated: true })
            }) as never)
            await bound.updatePersonWithPropertiesDiffForUpdate(person, { plan: 'pro' }, [], {}, 'd1')
            expect(memoOf().hasBaseline('1:7')).toBe(false)

            // A strong read served before the write applied delivers late;
            // filling the absence with it would let a later matching $set
            // classify as no-change against state the leader has moved past.
            memoOf().recordResolution(0, '1:d1', '1:7')
            memoOf().record(1, 'd1', { ...person, version: 4 }, 0, { readClass: 'update' })
            expect(memoOf().hasBaseline('1:7')).toBe(false)

            memoOf().record(1, 'd1', { ...person, version: 5 }, 0, { readClass: 'update' })
            expect(memoOf().viewOfPerson('1:7')?.version).toBe(5)
        })

        it('a stale read cannot refill the baseline a redirect dropped', async () => {
            const bound = store.forBatch(0)
            const survivor = { ...person, id: '9', version: 3 }
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd2', person: survivor },
            ] as never)
            repository.fetchPersonById.mockResolvedValue(survivor as never)
            await bound.fetchForUpdate(1, 'd2')

            await bound.applyEventOps(person, ops({ $set: { late: 'op' } }), 'd1')
            repository.updatePersonProperties.mockImplementationOnce((() =>
                Promise.reject(new NoRowsUpdatedError('merged away'))) as never)
            repository.updatePersonProperties.mockResolvedValue({
                person: { ...survivor, version: 9 },
                updated: true,
            } as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: survivor },
            ] as never)
            await bound.flush()

            // The redirect's write reached version 9 and dropped the
            // survivor's baseline. This read predates it; filling the absence
            // would revive the state those writes replaced, and a later event
            // diffing against it would be filtered into a lost write.
            memoOf().record(1, 'd2', { ...survivor, version: 3 }, 0, { readClass: 'update' })
            expect(memoOf().hasBaseline('1:9')).toBe(false)

            memoOf().record(1, 'd2', { ...survivor, version: 9 }, 0, { readClass: 'update' })
            expect(memoOf().viewOfPerson('1:9')?.version).toBe(9)
        })

        it('a create that finds a person the leader has lost memoizes nothing and stamps the death', async () => {
            // The leader answers null only for a destroyed person, and a
            // merge on another pod leaves no local stamp to catch it — this
            // read is the one death signal this pod gets, so it stamps like
            // the redirect's gone arm.
            repository.getOrCreatePersonByDistinctId.mockResolvedValue({ person, created: false } as never)
            repository.fetchPersonById.mockResolvedValue(null as never)
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

            expect(result.success && result.person?.id).toBe('7')
            expect(memoOf().resolutionOf('1:d1')).toBeUndefined()
            expect(memoOf().hasBaseline('1:7')).toBe(false)
            expect(memoOf().isDestroyed('1:7')).toBe(true)
            expect(memoOf().versionOf('1:d1')).toBeGreaterThan(0)
        })

        it('a filtered-only lane folded against a destroyed person writes instead of vanishing', async () => {
            // Ops diffing clean against the dead document prove nothing
            // about the survivor, so the lane must write and let the
            // tombstone redirect carry them there.
            person.properties = { $browser: 'Firefox' }
            repository.getOrCreatePersonByDistinctId.mockResolvedValue({ person, created: false } as never)
            repository.fetchPersonById.mockResolvedValue(null as never)
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

            await bound.applyEventOps(person, ops({ $set: { $browser: 'Chrome' } }, 'pageview'), 'd1')

            repository.updatePersonProperties.mockRejectedValueOnce(new NoRowsUpdatedError('merged away') as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: { ...person, id: '9', properties: {} } },
            ] as never)

            await bound.flush()

            const calls = repository.updatePersonProperties.mock.calls as unknown as [{ personId: string }][]
            expect(calls.length).toBeGreaterThan(1)
            expect(calls[calls.length - 1][0]).toMatchObject({ personId: '9' })
        })

        it('a redirect that ends gone stamps the id and the person like every removal', async () => {
            // Without the stamps, a read already on the wire reinstalls the
            // dead answer after the release, and the null-record guard then
            // refuses identity's truthful absence for the rest of the batch.
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            repository.updatePersonProperties.mockRejectedValue(new NoRowsUpdatedError('merged away') as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([] as never)

            await bound.flush()

            expect(memoOf().isDestroyed('1:7')).toBe(true)
            expect(memoOf().versionOf('1:d1')).toBeGreaterThan(0)
        })

        it('an evicted baseline floors the absence it leaves behind', async () => {
            // Eviction is a drop whose dropper held a version the leader
            // has reached; a read served before it and delivered after must
            // not refill the absence with older state.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, version: 6 } as never)
            const bound = store.forBatch(0)
            await bound.fetchForUpdate(1, 'd1')

            store.releaseBatch(0)
            expect(memoOf().hasBaseline('1:7')).toBe(false)

            memoOf().offerBaseline('1:7', { ...person, version: 4 }, 'leader-read')
            expect(memoOf().hasBaseline('1:7')).toBe(false)

            memoOf().offerBaseline('1:7', { ...person, version: 6 }, 'leader-read')
            expect(memoOf().viewOfPerson('1:7')?.version).toBe(6)
        })

        it('a direct diff update releases its baseline with the batch', async () => {
            // The diff path installs outside the lane protocol; without a
            // recorded edge the baseline would have no reference and no lane,
            // and nothing would ever evict it.
            const bound = store.forBatch(0)
            await bound.updatePersonWithPropertiesDiffForUpdate(person, { plan: 'pro' }, [], {}, 'd1')
            expect(memoOf().baselineCount).toBe(1)

            store.releaseBatch(0)

            expect(memoOf().baselineCount).toBe(0)
        })

        it('reconcile releases an id whose survivor a later merge destroyed', () => {
            const memo = (store as any).memo
            memo.recordResolution(0, '1:d9', '1:9')
            // Merge B destroyed 7 — the survivor merge A is about to name.
            ;(store as any).reconcileMergedPersons(1, [{ personKey: '1:7', distinctKey: '1:b-src' }], '1:11', 0)

            // Merge A's reconcile: source 9 destroyed, survivor 7 — but 7 is
            // itself dead, so repointing d9 at it would aim every later event
            // on d9 at a person that no longer exists.
            ;(store as any).reconcileMergedPersons(1, [{ personKey: '1:9', distinctKey: '1:d9' }], '1:7', 0)

            expect(memo.resolutionOf('1:d9')).toBeUndefined()
        })

        it('a merge on an unrelated id does not discard this read', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockImplementation((() => {
                // A merge for a different person, in a different team,
                // settles while this read is in flight.
                ;(store as any).reconcileMergedPersons(
                    2,
                    [{ personKey: '2:99', distinctKey: '2:elsewhere' }],
                    '2:98',
                    0
                )
                return Promise.resolve([{ teamId: 1, distinctId: 'd1', person }]) as never
            }) as never)
            repository.fetchPersonById.mockResolvedValue(person as never)

            await bound.fetchForUpdate(1, 'd1')

            // Discarding it would make the memo useless under merge load and
            // leave any loop that re-reads unable to make progress, which is
            // what a process-wide counter did.
            expect((store as any).memo.resolutionOf('1:d1')).toBe('1:7')
        })

        it('fails rather than folding onto a person the memo says the id left', async () => {
            const bound = store.forBatch(0)
            const other = { ...person, id: '9' }
            // d1 belongs to 9 and its document was dropped, so the fold has
            // to read. Every read is overtaken by a merge, so none records.
            ;(store as any).memo.recordResolution(0, '1:d1', '1:9')
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: other },
            ] as never)
            repository.fetchPersonById.mockImplementation((() => {
                ;(store as any).memo.bumpId('1:d1')
                return Promise.resolve(other)
            }) as never)

            // Folding onto person 7 would repoint d1 off 9 and onto a person
            // a merge left behind, and later events would compose on top.
            await expect(bound.applyEventOps(person, ops({ $set: { late: 'op' } }), 'd1')).rejects.toThrow(
                'belongs to another person'
            )
            expect((store as any).memo.resolutionOf('1:d1')).toBe('1:9')
        })

        it('a redirect drops the baseline of each person it proves gone', async () => {
            const bound = store.forBatch(0)
            const mid = { ...person, id: '9' }
            // The batch has read person 9, so it holds a document for it.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd2', person: mid },
            ] as never)
            repository.fetchPersonById.mockResolvedValue(mid as never)
            await bound.fetchForUpdate(1, 'd2')
            expect((store as any).memo.hasBaseline('1:9')).toBe(true)

            await bound.applyEventOps(person, ops({ $set: { k: 'A' } }), 'd1')
            // 7 is gone, the redirect resolves to 9, and 9 turns out to be
            // gone too; the pass after that resolves to nobody.
            repository.updatePersonProperties.mockRejectedValue(new NoRowsUpdatedError('merged away') as never)
            repository.resolvePersonsByDistinctIds
                .mockResolvedValueOnce([{ teamId: 1, distinctId: 'd1', person: mid }] as never)
                .mockResolvedValue([] as never)

            await bound.flush()

            // 9 was proved gone mid-chain. Leaving its document would serve
            // a dead person to every other id still naming it, and it is the
            // reason the 'gone' exit needs to drop only the lane's own.
            expect((store as any).memo.hasBaseline('1:9')).toBe(false)
        })

        it('a write in flight stays visible in the view until its answer lands', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { k: 'A' } }), 'd1')
            let releaseWrite: () => void = () => {}
            repository.updatePersonProperties.mockImplementation((() => {
                return new Promise((resolve) => {
                    releaseWrite = () =>
                        resolve({ person: { ...person, version: 3, properties: { k: 'A' } }, updated: true })
                })
            }) as never)
            const flushing = bound.flush()
            await new Promise((resolve) => setImmediate(resolve))

            // The op is on the wire and not yet in any document a service
            // would answer. Dropping it from the view here would show a
            // later event in this batch a person without its own write.
            expect((store as any).memo.viewOfPerson('1:7').properties).toMatchObject({ k: 'A' })

            releaseWrite()
            await flushing
            expect((store as any).memo.viewOfPerson('1:7').properties).toMatchObject({ k: 'A' })
        })

        it('a fold onto a dropped baseline does not invent a view for it', async () => {
            const bound = store.forBatch(0)
            const held = { ...person, properties: { k: 'x' } }
            // One event both writing and unsetting k resolves to gone,
            // because k was there before the op.
            const [afterOne] = await bound.applyEventOps(held, ops({ $set: { k: 'v' }, $unset: ['k'] }), 'd1')
            expect(afterOne.properties).toEqual({})
            // A redirect on another lane drops this person's document while
            // that op is still unsent.
            ;(store as any).memo.dropBaseline('1:7')

            // The caller folds again holding the view it was just given.
            await bound.applyEventOps(afterOne, ops({ $set: { j: 'B' } }), 'd1')
            // Taking the caller's person as the baseline would replay ops it
            // already contains, and the pair resolves the other way over a
            // document that has taken it. With no baseline there is no view
            // to serve, so the read goes to the leader.
            expect((store as any).memo.hasBaseline('1:7')).toBe(false)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: held },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...held, version: 9 } as never)

            await bound.fetchForUpdate(1, 'd1')

            // What the leader will hold once the lane lands: k gone, j set.
            expect((store as any).memo.viewOfPerson('1:7').properties).toEqual({ j: 'B' })
        })

        it('a read landing mid-write does not replay the op already on the wire', async () => {
            const bound = store.forBatch(0)
            const held = { ...person, properties: { k: 'x' } }
            // One event both writing and unsetting the key resolves to gone,
            // because the key was there before the op. Replaying it over a
            // document that already took it reads the other way.
            await bound.applyEventOps(held, ops({ $set: { k: 'v' }, $unset: ['k'] }), 'd1')
            let releaseWrite: () => void = () => {}
            repository.updatePersonProperties.mockImplementation((() => {
                return new Promise((resolve) => {
                    releaseWrite = () => resolve({ person: { ...held, version: 3, properties: {} }, updated: true })
                })
            }) as never)
            const flushing = bound.flush()
            await new Promise((resolve) => setImmediate(resolve))

            // The leader has applied it; a sibling read sees the result.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd2', person: held },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...held, version: 3, properties: {} } as never)
            await bound.fetchForUpdate(1, 'd2')

            // Asserted while the write is still on the wire, which is the
            // whole window: counting the sent op again would put back the key
            // the leader has just removed, and an event arriving here would
            // diff against it.
            expect((store as any).memo.viewOfPerson('1:7').properties).toEqual({})

            releaseWrite()
            await flushing
            expect((store as any).memo.viewOfPerson('1:7').properties).toEqual({})
        })

        it('a refused write leaves nothing asserted that the leader never took', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { k: 'A' } }), 'd1')
            repository.updatePersonProperties.mockRejectedValueOnce(
                new PersonhogPropertiesSizeError('too big', 1, '7') as never
            )
            await bound.flush()
            repository.updatePersonProperties.mockClear()

            await bound.applyEventOps(person, ops({ $set: { k: 'A' } }), 'd1')
            await bound.flush()

            // A view still counting the refused ops would make this diff
            // clean against a value the leader never took, and the write
            // would be filtered away rather than retried on its own.
            expect(repository.updatePersonProperties).toHaveBeenCalledWith(
                expect.objectContaining({ personId: '7', setProperties: { k: 'A' } }),
                expect.anything()
            )
        })

        it('an id repointed by a redirect still folds onto the survivor', async () => {
            const bound = store.forBatch(0)
            // Version above the redirect's own write answers: leader versions
            // are monotonic, so a post-redirect read can never come back
            // below what the redirect's writes reached.
            const survivor = { ...person, id: '9', version: 3 }
            // The batch knows the survivor, then a lane whose person was
            // merged away redirects its ops onto it.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd2', person: survivor },
            ] as never)
            repository.fetchPersonById.mockResolvedValue(survivor as never)
            await bound.fetchForUpdate(1, 'd2')

            await bound.applyEventOps(person, ops({ $set: { early: 'op' } }), 'd1')
            repository.updatePersonProperties.mockImplementationOnce((() =>
                Promise.reject(new NoRowsUpdatedError('merged away'))) as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: survivor },
            ] as never)
            await bound.flush()

            // d1 belongs to the survivor now. A caller still holding the
            // person it read before the merge must not get it back.
            const [landed] = await bound.applyEventOps(person, ops({ $set: { late: 'op' } }), 'd1')
            expect(landed.id).toBe('9')
        })

        it('a redirect drops the survivor projection it just made stale', async () => {
            const bound = store.forBatch(0)
            // The survivor is known to the batch, then a lane whose person
            // was merged away writes its ops onto it.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd2', person: { ...person, id: '9' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '9' } as never)
            await bound.fetchForUpdate(1, 'd2')
            expect((store as any).memo.hasBaseline('1:9')).toBe(true)

            await bound.applyEventOps(person, ops({ $set: { late: 'op' } }), 'd1')
            repository.updatePersonProperties.mockImplementationOnce((() =>
                Promise.reject(new NoRowsUpdatedError('merged away'))) as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: { ...person, id: '9' } },
            ] as never)

            await bound.flush()

            // Its own lane cannot know about those ops and this batch cannot
            // order the two together, so the leader answers the next read.
            expect((store as any).memo.hasBaseline('1:9')).toBe(false)
        })

        it('a redirect keeps a survivor baseline that already contains its writes', async () => {
            const bound = store.forBatch(0)
            // The survivor's own lane wrote concurrently and installed the
            // document its write produced, past anything this redirect lands.
            ;(store as any).memo.offerBaseline(
                '1:9',
                { ...person, id: '9', version: 10, properties: { own: 'newer' } },
                'own-write'
            )

            await bound.applyEventOps(person, ops({ $set: { late: 'op' } }), 'd1')
            repository.updatePersonProperties.mockImplementationOnce((() =>
                Promise.reject(new NoRowsUpdatedError('merged away'))) as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: { ...person, id: '9' } },
            ] as never)

            await bound.flush()

            // The redirect's writes answered version 2, and a document at
            // version 10 already contains them. Dropping it would discard
            // the newer state and floor at 2, letting a read served between
            // the two writes reinstall a document missing the later one.
            expect((store as any).memo.viewOfPerson('1:9')).toMatchObject({
                version: 10,
                properties: { own: 'newer' },
            })
        })

        it('a discarded projection is rebuilt from the leader plus what the lane has not sent', async () => {
            const bound = store.forBatch(0)
            // The lane holds k='A' unsent while the leader still answers the
            // value it replaces.
            await bound.applyEventOps(person, ops({ $set: { k: 'A' } }), 'd1')
            ;(store as any).memo.dropBaseline('1:7')
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({
                ...person,
                version: 9,
                properties: { k: 'old' },
            } as never)

            await bound.fetchForUpdate(1, 'd1')

            // Filling the hole with bare leader state would make a later
            // event setting k='old' diff clean and be filtered away, and the
            // lane's own write would then land 'A' as the customer's final
            // value instead of 'old'.
            expect((store as any).memo.viewOfPerson('1:7')).toMatchObject({
                version: 9,
                properties: { k: 'A' },
            })
        })

        it('a merge landing inside the fold read does not fold onto the person it destroyed', async () => {
            const bound = store.forBatch(0)
            const doomed = { ...person, id: '9' }
            const survivor = { ...person, id: '11' }
            // d1 names 9, whose document a redirect discarded, so the fold
            // has to read. The caller still holds the person it resolved
            // before any of this.
            ;(store as any).memo.recordResolution(0, '1:d1', '1:9')
            let releaseFetch = (): void => {}
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: doomed },
            ] as never)
            repository.fetchPersonById.mockReturnValue(
                new Promise((resolve) => {
                    releaseFetch = () => resolve(doomed)
                }) as never
            )

            const folding = bound.applyEventOps(person, ops({ $set: { late: 'op' } }), 'd1')
            await new Promise((resolve) => setImmediate(resolve))
            // A merge completes while that read is in flight: 9 is gone and
            // d1 belongs to 11.
            ;(store as any).memo.bumpId('1:d1')
            ;(store as any).memo.repointResolution('1:d1', '1:11')
            ;(store as any).memo.offerBaseline('1:11', survivor, 'own-write')
            releaseFetch()
            const [landed] = await folding

            // Answering with the read would name the destroyed person as the
            // id's owner and repoint d1 off the survivor back onto it.
            expect(landed.id).toBe('11')
            expect((store as any).memo.resolutionOf('1:d1')).toBe('1:11')
        })

        it('a size rejection mid-redirect still heals the id it resolved', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            // The person is merged away and the survivor rejects the only
            // unit on size. The resolve still proved where the id belongs.
            repository.updatePersonProperties.mockImplementation(((request: { personId: string }) =>
                request.personId === '7'
                    ? Promise.reject(new NoRowsUpdatedError('merged away'))
                    : Promise.reject(new PersonhogPropertiesSizeError('too big', 1, '9'))) as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: { ...person, id: '9' } },
            ] as never)

            await bound.flush()

            // Left pointing at the dead person, every later event in the
            // batch would fold onto it and pay the redirect again.
            expect((store as any).memo.resolutionOf('1:d1')).toBe('1:9')
        })

        it('a fetch parked across a destroying merge folds onto the survivor, not what it read', async () => {
            const bound = store.forBatch(0)
            const survivor = { ...person, id: '7', uuid: 'target-uuid', properties: { plan: 'survivor' } }
            const doomed = { ...person, id: '9', uuid: 'source-uuid', properties: { plan: 'source' } }
            let releaseFetch = (): void => {}
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: doomed },
            ] as never)
            repository.fetchPersonById
                .mockReturnValueOnce(
                    new Promise((resolve) => {
                        releaseFetch = () => resolve(doomed)
                    }) as never
                )
                // The merge's survivor refresh reads the leader afterwards.
                .mockResolvedValue(survivor as never)
            const fetching = bound.fetchForUpdate(1, 'anon-1')

            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
            } as never)
            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                eventUuid: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })

            // The read completed before the merge, so it answers the person
            // the merge destroyed. Nothing may be written against it.
            releaseFetch()
            const fetched = await fetching
            expect(fetched?.id).toBe('9')

            const [landed] = await bound.applyEventOps(fetched!, ops({ $set: { late: 'op' } }), 'anon-1')
            expect(landed.id).toBe('7')
        })

        it('an id whose person was merged twice folds onto the last survivor', async () => {
            const bound = store.forBatch(0)
            const first = { ...person, id: '9', uuid: 'first-uuid', properties: { plan: 'first' } }
            const second = { ...person, id: '7', uuid: 'second-uuid', properties: { plan: 'second' } }
            const third = { ...person, id: '11', uuid: 'third-uuid', properties: { plan: 'third' } }
            // A real identity graph, repointed by each merge. A fixed mock row
            // answers every resolve with the same person, and the merge's own
            // fence resolve then writes that answer into the memo.
            const persons = new Map([
                ['9', first],
                ['7', second],
                ['11', third],
            ])
            const graph = new Map([['anon-1', '9']])
            repository.resolvePersonsByDistinctIds.mockImplementation(
                (keys: { distinctId: string }[]) =>
                    Promise.resolve(
                        keys.map(({ distinctId }) => {
                            const personId = graph.get(distinctId)
                            return { teamId: 1, distinctId, person: personId ? persons.get(personId) : null }
                        })
                    ) as never
            )
            repository.fetchPersonById.mockImplementation(((_t: number, id: string) =>
                Promise.resolve(persons.get(id) ?? null)) as never)
            await bound.fetchForUpdate(1, 'anon-1')

            const merge = (targetDistinctId: string, sourceDistinctId: string, eventUuid: string) => ({
                teamId: 1,
                targetDistinctId,
                sources: [{ distinctId: sourceDistinctId, eventUuid }],
                eventOps: ops({}, '$identify'),
                eventUuid,
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })
            const settle = (survivor: InternalPerson, sourceDistinctId: string, sourcePersonId: string) => {
                for (const [distinctId, personId] of graph) {
                    if (personId === sourcePersonId) {
                        graph.set(distinctId, survivor.id)
                    }
                }
                repository.mergePersons = jest.fn().mockResolvedValue({
                    survivor,
                    results: [{ sourceDistinctId, outcome: 'merged', sourcePersonId }],
                } as never)
            }

            graph.set('d1', '7')
            settle(second, 'anon-1', '9')
            await bound.mergePersons(merge('d1', 'anon-1', 'event-uuid'))
            graph.set('d2', '11')
            settle(third, 'd1', '7')
            await bound.mergePersons(merge('d2', 'd1', 'event-uuid-2'))

            // Each merge repoints the ids of the person it destroyed, so an id
            // from the head of the chain has to reach its end rather than a
            // person from the middle.
            const [landed] = await bound.applyEventOps(first, ops({ $set: { late: 'op' } }), 'anon-1')
            expect(landed.id).toBe('11')
        })

        it('an attach-only merge still invalidates a fetch that resolved before it', async () => {
            const bound = store.forBatch(0)
            // The response survivor is the sync plane's own resolve; the
            // leader has moved past it, which the refresh discovers.
            const responseSurvivor = { ...person, properties: { plan: 'folded' }, version: 5 }
            const leaderNow = { ...person, properties: { plan: 'refreshed' }, version: 6 }
            // The fetch resolves the id, then parks on its by-id read. The
            // merge runs while it is parked and destroys nothing, which is
            // every $identify that attaches an unseen id.
            let releaseFetch = (): void => {}
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById
                .mockReturnValueOnce(
                    new Promise((resolve) => {
                        releaseFetch = () => resolve(person)
                    }) as never
                )
                .mockResolvedValue(leaderNow as never)
            const fetching = bound.fetchForUpdate(1, 'd1')

            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: responseSurvivor,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'attached', sourcePersonId: null }],
            } as never)
            const result = await bound.mergePersons(mergeReq())

            // The response document never installs; the refresh's leader
            // read is what the batch classifies against, and it is what the
            // caller gets back to fold this event with.
            expect(result.survivor).toMatchObject({ properties: { plan: 'refreshed' }, version: 6 })
            const memo = (store as any).memo
            expect(memo.snapshot(memo.lookup(1, 'd1', 'update'))).toMatchObject({
                properties: { plan: 'refreshed' },
                version: 6,
            })

            // The read predates the merge, and its document predates the
            // version the merge's resolve proved the leader passed, so the
            // floor and the version guard refuse it.
            releaseFetch()
            await fetching
            expect(memo.snapshot(memo.lookup(1, 'd1', 'update'))).toMatchObject({ version: 6 })
        })

        it('a fence releasing mid-round cannot make the flush ack over a deferred lane', async () => {
            const narrowStore = new PersonhogPersonsStore(repository, { maxConcurrentUpdates: 1 })
            const bound = narrowStore.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            // Three lanes, one slot. 7 starts under the fence and defers; the
            // merge releases while 10's RPC holds the round open, so the
            // round's scan finds 7 neither fenced nor in flight.
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
                        releaseMerge = () => resolve({ survivor: person, results: [] })
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
            // 7 started under the live fence and deferred; the merge waited
            // that out and wrote the lane itself rather than leaving it for a
            // later round to find. 10 is still on the wire.
            expect(written).toContain('7')
            expect(written).toContain('8')
            // The merge resolves and releases its fence while 10 is still on
            // the wire — the exact window where 7 is invisible to a
            // parked-only scan.
            releaseMerge()
            await merging
            releases.get('10')?.()
            await flushing

            // Whatever the interleaving, nothing acks over unwritten ops.
            expect(written).toEqual(expect.arrayContaining(['8', '10', '7']))
            expect((narrowStore as any).entries.get('1:7')?.segments ?? []).toHaveLength(0)
        })

        it('a round that deferred keeps going even when nothing is parked at the exit check', async () => {
            // The loop keys off what the round left behind, not what is
            // parked at this instant; reading the instant acks over ops a
            // fold parked after the fence lifted.
            const narrowStore = new PersonhogPersonsStore(repository, { maxConcurrentUpdates: 1 })
            const bound = narrowStore.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            await bound.applyEventOps({ ...person, id: '8', uuid: 'u8' }, ops({ $set: { a: '1' } }), 'other-1')
            await bound.applyEventOps(person, ops({ $set: { plan: 'held' } }), 'd1')
            await bound.applyEventOps({ ...person, id: '10', uuid: 'u10' }, ops({ $set: { c: '3' } }), 'other-2')

            const releases = new Map<string, () => void>()
            const written: { personId: string; setProperties: Record<string, unknown> }[] = []
            repository.updatePersonProperties.mockImplementation(((request: {
                personId: string
                setProperties: Record<string, unknown>
            }) => {
                written.push({ personId: request.personId, setProperties: request.setProperties })
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
                        releaseMerge = () => resolve({ survivor: person, results: [] })
                    })
            )

            const flushing = bound.flush()
            await new Promise((resolve) => setTimeout(resolve, 0))
            const merging = bound.mergePersons(mergeReq())
            await new Promise((resolve) => setTimeout(resolve, 0))
            releases.get('8')?.()
            await new Promise((resolve) => setTimeout(resolve, 0))

            // The merge settles and drops its fence while 10 still holds the
            // round open, then a later event folds fresh ops onto 7. At the
            // exit check 7 is unfenced, not in flight, and has segments.
            releaseMerge()
            await merging
            await bound.applyEventOps(person, ops({ $set: { plan: 'after-merge' } }), 'd1')
            expect((narrowStore as any).fences.has('1:7')).toBe(false)
            expect((narrowStore as any).entries.get('1:7')?.segments).toHaveLength(1)

            releases.get('10')?.()
            await flushing

            expect((narrowStore as any).entries.get('1:7')?.segments ?? []).toHaveLength(0)
            expect(written.filter((call) => call.personId === '7').at(-1)?.setProperties).toEqual({
                plan: 'after-merge',
            })
        })

        it('a merge waits for a redirect already writing to its survivor', async () => {
            const bound = store.forBatch(0)
            // An external merge destroyed lane 9's person, so its redirect
            // resolves survivor 7 and goes on the wire. A local merge fencing
            // 7 must wait it out, or its newer writes land first and the
            // redirect's older raw $set overwrites them.
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
                return Promise.resolve({ survivor: person, results: [] })
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

    it('a merge whose redirect meets another merge’s fence refuses instead of waiting', async () => {
        // Two merges cross: the second holds a fence on person 7, and the
        // first is redirecting a lane that resolves to 7. Waiting here would
        // be waiting under a fence of our own.
        personhogStoreFlushCounter.reset()
        const bound = store.forBatch(0)
        let laneMergedAway = false
        repository.resolvePersonsByDistinctIds.mockImplementation(((keys: { distinctId: string }[]) =>
            Promise.resolve(
                keys.map((key) => {
                    // 'anon-a' names person 9 until the leader loses it, and
                    // the survivor it redirects to is the person the other
                    // merge holds.
                    const id = key.distinctId.endsWith('-b') || laneMergedAway ? '7' : '9'
                    return { teamId: 1, distinctId: key.distinctId, person: { ...person, id } }
                })
            )) as never)
        repository.mergePersons = jest
            .fn()
            .mockImplementation((request: { targetDistinctId: string }) =>
                request.targetDistinctId === 'd-b'
                    ? new Promise(() => {})
                    : Promise.resolve({ survivor: person, results: [] })
            ) as never
        repository.updatePersonProperties.mockImplementation((() => {
            laneMergedAway = true
            return Promise.reject(new NoRowsUpdatedError('merged away'))
        }) as never)

        const mergeReq = (suffix: string) => ({
            teamId: 1,
            targetDistinctId: `d-${suffix}`,
            sources: [{ distinctId: `anon-${suffix}`, eventUuid: `event-${suffix}` }],
            eventOps: ops({}, '$identify'),
            eventUuid: `event-${suffix}`,
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        // Fences person 7 and never returns, so the fence stands throughout.
        // The catch is unreachable while that promise never settles, and is
        // here so a broken premise surfaces as the assertion below rather
        // than as an unhandled rejection.
        void bound.mergePersons(mergeReq('b')).catch(() => {})
        await new Promise((resolve) => setTimeout(resolve, 0))
        // Asserted rather than assumed: everything after this depends on the
        // fence already standing, and without the check a tick that turned
        // out to be too short would fail somewhere less obvious.
        expect((store as any).fences.has('1:7')).toBe(true)
        await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'stale' } }), 'anon-a')

        await expect(bound.mergePersons(mergeReq('a'))).rejects.toThrow(PersonMergeCallFailedError)
        const outcomes = (await personhogStoreFlushCounter.get()).values.map((value) => value.labels.outcome)
        expect(outcomes).toContain('redirect_fenced_during_merge')
    })

    describe('parity with the Postgres backend', () => {
        const mergeReq = () => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
            eventOps: ops({}, '$identify'),
            eventUuid: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('folds onto the survivor when the merge that destroyed the person already released', async () => {
            // A caller resolves its person, a merge destroys it and releases,
            // and only then does the fold arrive. No fence is left to wait
            // on, so nothing but the memo can tell the person is gone.
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            repository.fetchPersonById.mockImplementation(((_t: number, id: string) =>
                Promise.resolve({ ...person, id })) as never)
            const stale = (await bound.fetchForUpdate(1, 'anon-1'))!
            expect(stale.id).toBe('9')

            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, id: '7' },
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
            })
            await bound.mergePersons(mergeReq())
            expect((store as any).fences.size).toBe(0)

            const [projected] = await bound.applyEventOps(stale, ops({ $set: { plan: 'after' } }), 'anon-1')

            // The ops belong to the survivor, and the id must not be pointed
            // back at the person the merge destroyed.
            expect(projected.id).toBe('7')
            expect((store as any).entries.has('1:9')).toBe(false)
            expect((store as any).memo.resolutionOf('1:anon-1')).toBe('1:7')
        })

        it.each([
            ['the move limit', 'skipped_move_limit', 'limit'],
            ['a lifecycle conflict', 'skipped_conflict', 'conflict'],
        ])('a fold that skipped one source on %s aborts after keeping what merged', async (_case, skip, reason) => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, version: 7 },
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' },
                    { sourceDistinctId: 'anon-2', outcome: skip },
                ],
            })

            const result = await bound.mergePersons({
                ...mergeReq(),
                sources: [
                    { distinctId: 'anon-1', eventUuid: 'event-uuid' },
                    { distinctId: 'anon-2', eventUuid: 'event-uuid-2' },
                ],
            })

            // Postgres's fold is all-or-nothing, so a skipped source there
            // falls back to its own sequential merge and its own durability
            // decision. Executing here instead would ack anon-2's event with
            // no merge behind it.
            expect(result.foldAborted).toBe(reason)
            expect(result.survivor).toBeNull()
            // The abort does not unwind what the saga durably did: anon-1's
            // person really merged, so the memo must already reflect it, or
            // later events fold onto the destroyed person.
            expect((store as any).memo.isDestroyed('1:9')).toBe(true)
            expect((store as any).memo.resolutionOf('1:anon-1')).toBe('1:7')
        })

        it('reports a fold whose every source conflicted as an abort, not a success', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, id: '7' },
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'skipped_conflict' },
                    { sourceDistinctId: 'anon-2', outcome: 'skipped_conflict' },
                ],
            })

            const result = await bound.mergePersons({
                ...mergeReq(),
                sources: [
                    { distinctId: 'anon-1', eventUuid: 'event-uuid' },
                    { distinctId: 'anon-2', eventUuid: 'event-uuid-2' },
                ],
            })

            // The saga still answers a survivor here, so without the abort
            // the caller reads a fold that merged nothing as executed and
            // acks every event in the run. Postgres falls back to per-event
            // merges for the same condition, and each of those retries.
            expect(result.foldAborted).toBe('conflict')
            expect(result.survivor).toBeNull()
            expect(repository.mergePersons).toHaveBeenCalledTimes(1)
        })

        it('reports a fold the leader definitively refused as an abort, not a success', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, id: '7' },
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'skipped_refused' },
                    { sourceDistinctId: 'anon-2', outcome: 'skipped_refused' },
                ],
            })

            const result = await bound.mergePersons({
                ...mergeReq(),
                sources: [
                    { distinctId: 'anon-1', eventUuid: 'event-uuid' },
                    { distinctId: 'anon-2', eventUuid: 'event-uuid-2' },
                ],
            })

            // An aborted response still carries a survivor, so without the
            // abort flag the caller would read a fold that merged nothing
            // as executed and misattribute every event in the run.
            expect(result.foldAborted).toBe('refused')
            expect(result.survivor).toBeNull()
        })

        it('carries ops its own merge missed to the survivor rather than dropping them', async () => {
            // The reference backend folds a source's pending properties into
            // the survivor before deleting the row, so ops that missed the
            // fold are not lost there and must not be lost here. The redirect
            // is what carries them.
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '9' } as never)
            await bound.fetchForUpdate(1, 'anon-1')
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'stale' } }), 'anon-1')
            expect((store as any).entries.get('1:9')?.segments).toHaveLength(1)

            // The lane goes unwritten: the leader fence naming this merge's
            // own saga is the one refusal the pre-merge write proceeds past.
            repository.updatePersonProperties.mockRejectedValueOnce(
                new PersonhogFencedError('fenced', '9', mergeOpIdFromRequest(1, 'event-uuid', ['anon-1'], 10_000))
            )
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, id: '7' },
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
            })
            await bound.mergePersons(mergeReq())

            // Still pending: reconcile leaves them, and the flush redirects.
            expect((store as any).entries.get('1:9')?.segments).toHaveLength(1)
            repository.updatePersonProperties.mockReset()
            repository.updatePersonProperties.mockImplementation((({ personId }: { personId: string }) =>
                personId === '9'
                    ? Promise.reject(new NoRowsUpdatedError('merged away'))
                    : Promise.resolve({ person: { ...person, id: '7' }, updated: true })) as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '7' } },
            ] as never)

            await bound.flush()

            const landed = repository.updatePersonProperties.mock.calls
                .filter(([request]) => request.personId === '7')
                .map(([request]) => request.setProperties)
            expect(landed).toContainEqual({ plan: 'stale' })
        })

        it('keeps a lane the server never named, since the memo can be wrong about it', async () => {
            // No sourcePersonId, so the person is only inferred from this
            // pod's own memo. A replayed verdict or another pod's merge can
            // make that name a live person, and discarding is irreversible,
            // so the ops stay and the write redirects if the person did die.
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '9' } as never)
            await bound.fetchForUpdate(1, 'anon-1')
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'stale' } }), 'anon-1')

            repository.updatePersonProperties.mockRejectedValueOnce(
                new PersonhogFencedError('fenced', '9', mergeOpIdFromRequest(1, 'event-uuid', ['anon-1'], 10_000))
            )
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, id: '7' },
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
            })
            await bound.mergePersons(mergeReq())

            expect((store as any).entries.get('1:9')?.segments).toHaveLength(1)
        })

        it('keeps a lane buffered when the merge call returns no verdict', async () => {
            // Postgres keeps its pending updates across a rolled-back merge.
            // Nothing here knows whether the source died, so discarding would
            // lose writes for a merge that never happened.
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '9' } as never)
            await bound.fetchForUpdate(1, 'anon-1')
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'stale' } }), 'anon-1')
            // Same bounce as above, so the lane is still buffered when the
            // call goes out and its fate is what this pins.
            repository.updatePersonProperties.mockRejectedValueOnce(
                new PersonhogFencedError('fenced', '9', mergeOpIdFromRequest(1, 'event-uuid', ['anon-1'], 10_000))
            )
            repository.mergePersons = jest.fn().mockRejectedValue(new Error('no verdict'))

            await expect(bound.mergePersons(mergeReq())).rejects.toThrow(PersonMergeCallFailedError)
            expect((store as any).entries.get('1:9')?.segments).toHaveLength(1)
        })
    })

    describe('round-3 closures', () => {
        const mergeReq = (sources = ['anon-1']) => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: sources.map((distinctId) => ({ distinctId, eventUuid: 'event-uuid' })),
            eventOps: ops({}, '$identify'),
            eventUuid: 'event-uuid',
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
                        releaseMerge = () => resolve({ survivor: person, results: [] })
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
            // 7's queued write began under the fence and deferred rather than
            // racing the saga. The merge waited that deferral out and wrote
            // the lane itself, so the ops are durable before its request goes
            // out — not left for a later drain to chase.
            expect(written).toEqual(['8', '7'])
            expect(repository.mergePersons).toHaveBeenCalledTimes(1)

            releaseMerge()
            await merging
            await flushing
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
                    fenceRelease = (store as any).fencePersons(['1:7']).release
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
            eventUuid: 'event-uuid',
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
                return Promise.resolve({ survivor: person, results: [] })
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
    })

    describe('convergence closures', () => {
        const mergeReq = (sources = ['anon-1']) => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: sources.map((distinctId) => ({ distinctId, eventUuid: 'event-uuid' })),
            eventOps: ops({}, '$identify'),
            eventUuid: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('a merge writes the lanes it fences before its request goes out', async () => {
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
                        releaseMerge = () => resolve({ survivor: person, results: [] })
                    })
            )
            const merging = boundB.mergePersons(mergeReq())
            await new Promise((resolve) => setTimeout(resolve, 0))

            // Batch A must not ack over ops nobody has written. The merge
            // writes the lane itself before its request goes out, so by the
            // time A flushes the ops are durable — the guarantee holds
            // through the write rather than through a wait.
            expect(repository.updatePersonProperties).toHaveBeenCalled()
            expect((store as any).entries.get('1:7')?.segments ?? []).toHaveLength(0)
            let flushSettled = false
            const flushing = boundA.flush().then(() => {
                flushSettled = true
            })
            await new Promise((resolve) => setTimeout(resolve, 0))
            // A may resolve while the merge is still on the wire, and that is
            // safe precisely because the merge already wrote these ops: the
            // ack covers durable state, which is what the invariant asks.
            expect(flushSettled).toBe(true)

            releaseMerge()
            await merging
            await flushing
            expect((store as any).entries.get('1:7')?.segments ?? []).toHaveLength(0)
        })

        it('a redirect waits out the person\u2019s fence before writing anywhere', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { plan: 'pre' } }), 'anon-2')

            // The write is captured before any fence exists, and the merge
            // fences and reconciles while it is on the wire. Without the fence
            // wait the redirect resolves mid-merge and writes pre-merge ops
            // raw to the survivor.
            let fenceRelease: () => void = () => {}
            repository.updatePersonProperties.mockImplementationOnce((() => {
                fenceRelease = (store as any).fencePersons(['1:9']).release
                ;(store as any).reconcileMergedPersons(1, [{ personKey: '1:9', distinctKey: '1:anon-2' }], '1:7', 0)
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
            // Reconcile leaves a lane a write already owns, so these ops
            // survive and travel to the survivor as they stand.
            const redirected = repository.updatePersonProperties.mock.calls
                .map(([request]) => request)
                .filter((request) => request.personId === '7')
            expect(redirected[0].setProperties).toEqual({ plan: 'pre' })
            expect(redirected[0].setOnceProperties).toEqual({})
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
            eventUuid: 'event-uuid',
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
            })

            await bound.mergePersons(mergeReq())

            // The captured belief puts person 5 in the fenced set, so the
            // pre-merge write reaches its lane and the saga folds ops that
            // would otherwise have had to chase the survivor afterwards,
            // leaving its lane empty.
            const written = repository.updatePersonProperties.mock.calls.map(([call]) => call.personId)
            expect(written).toContain('5')
            expect((store as any).entries.get('1:5')?.segments ?? []).toHaveLength(0)
        })

        it('a post-verdict processing bug surfaces as itself, not as a call failure', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
            })
            const bug = new Error('post-verdict bug')
            jest.spyOn(store as any, 'reconcileMergedPersons').mockImplementation(() => {
                throw bug
            })

            // Mislabeling this as a call failure would point responders at
            // the network for a merge that answered fine.
            const surfaced = await bound.mergePersons(mergeReq()).catch((error: unknown) => error)
            expect(surfaced).toBe(bug)
            expect(surfaced).not.toBeInstanceOf(PersonMergeCallFailedError)
        })
    })

    describe('residual closures', () => {
        const mergeReq = (sources = ['anon-1']) => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: sources.map((distinctId) => ({ distinctId, eventUuid: 'event-uuid' })),
            eventOps: ops({}, '$identify'),
            eventUuid: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('fences a source person this pod never touched', async () => {
            const bound = store.forBatch(0)
            // The memo has never seen anon-1; only the merge's own resolve
            // can discover its person. Without that, a first-touch fold
            // landing mid-merge races the request unfenced.
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
            // The fold waited the merge out, so reconcile never saw its lane.
            // It writes as the post-merge write it is, raw through the
            // redirect path.
            const lane = (store as any).entries.get('1:9')
            expect(lane.segments.at(-1).set).toEqual({ raced: 'yes' })
        })

        it('a prefetch response crossing a merge fills nothing', async () => {
            const boundPrefetch = store.forBatch(0)
            const bound = store.forBatch(1)
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '9' } as never)
            await bound.fetchForUpdate(1, 'anon-1')

            // The prefetch resolves anon-2 to the doomed person, and a merge
            // destroys it while the leader read is in flight. The late fill
            // must not reinstall the dead person under anon-2.
            repository.resolvePersonsByDistinctIds.mockImplementation(((keys: { distinctId: string }[]) =>
                Promise.resolve(
                    keys
                        .filter((key) => key.distinctId === 'anon-2')
                        .map((key) => ({ teamId: 1, distinctId: key.distinctId, person: { ...person, id: '9' } }))
                )) as never)
            // Only the prefetch's own read runs the merge; the merge's
            // survivor refresh calls this mock too and must not recurse.
            let mergeRan = false
            repository.fetchPersonById.mockImplementation((async (_teamId: number, personId: string) => {
                if (!mergeRan) {
                    mergeRan = true
                    repository.mergePersons = jest.fn().mockResolvedValue({
                        survivor: person,
                        results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
                    })
                    await bound.mergePersons(mergeReq())
                }
                return { ...person, id: personId }
            }) as never)
            await store.prefetchPersons([{ teamId: 1, distinctId: 'anon-2', batchId: 0 }])

            expect((store as any).memo.resolutionOf('1:anon-2')).not.toBe('1:9')
            void boundPrefetch
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

            // Identity lags the leader and does not know k yet. State is
            // shared per person, so replacing here would give d1's next update
            // read a baseline without k, and an $unset k would classify
            // no-change and be suppressed.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd2', person: { ...person, properties: {} } },
            ] as never)
            await bound.fetchForChecking(1, 'd2')

            const seen = await bound.fetchForUpdate(1, 'd1')
            expect(seen?.properties).toEqual({ k: 'leader' })
        })

        it('a caller mutating a fetched absent-person fallback cannot corrupt the memo', async () => {
            const bound = store.forBatch(0)
            // The absent-person fallback was the one fetch branch that
            // returned the shared memo object, so a caller mutating its
            // answer corrupted the memo.
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'd2', person: { ...person, id: '8', properties: { plan: 'free' } } },
            ] as never)
            await bound.fetchForChecking(1, 'd2')
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([] as never)
            const fallback = await bound.fetchForUpdate(1, 'd2')
            expect(fallback).not.toBeNull()
            if (fallback) {
                fallback.properties.stamped = 'by-caller'
            }

            expect((store as any).memo.viewOfPerson('1:8')?.properties.stamped).toBeUndefined()
        })

        it('derives a valid op uuid from a salted op id', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
            })
            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                eventUuid: 'event-uuid#conflict1',
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
        it('a fold fails rather than proceeding past a fence whose merge never settles', async () => {
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
                    eventUuid: 'event-uuid',
                    allowIdentifiedSources: false,
                    mergeMode: createDefaultSyncMergeMode(),
                    createdAtMs: 3_600_000,
                })
                // The fence installs after the merge's own resolve.
                await jest.advanceTimersByTimeAsync(0)

                // Folding past the fence would land ops the saga is still
                // deciding, with a precedence nothing can repair. Failing
                // costs a round trip and loses nothing.
                const fold = bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
                const settled = fold.then(
                    () => 'folded' as const,
                    () => 'failed' as const
                )
                await jest.advanceTimersByTimeAsync(200_000)
                expect(await settled).toBe('failed')
                const waits = (await personhogStoreFenceCounter.get()).values
                expect(waits.map((wait) => wait.labels.outcome)).toContain('timeout')
                // The store's only give-up site. Nothing else throws on a
                // fence that never releases, so a wait that stops reporting
                // here is a wait that stops giving up.
                expect(waits.map((wait) => wait.labels.outcome)).toContain('wait_deadline_exceeded')
            } finally {
                jest.useRealTimers()
            }
        })

        it('the fence-wait ceiling stays above the merge deadline times its retries', () => {
            // The load-bearing relation of the derivation: the ceiling must
            // exceed a legitimately slow merge's whole transport-retried
            // hold, or every waiter gives up mid-hold and the leak alarm
            // fires on healthy merges.
            expect(derivedFenceWaitMs(35_000)).toBeGreaterThan(35_000 * 3)
            expect(derivedFenceWaitMs(60_000)).toBeGreaterThan(60_000 * 3)
        })

        it('a fold waits out a legitimately slow merge instead of failing at the old ceiling', async () => {
            // A merge under its transport-retried deadline can hold its
            // fence far past thirty seconds while succeeding; a lower wait
            // ceiling would convert that slow saga into a batch failure.
            jest.useFakeTimers()
            try {
                const bound = store.forBatch(0)
                repository.resolvePersonsByDistinctIds.mockResolvedValue([
                    { teamId: 1, distinctId: 'd1', person },
                ] as never)
                repository.fetchPersonById.mockResolvedValue({ ...person } as never)
                await bound.fetchForUpdate(1, 'd1')
                repository.mergePersons = jest.fn().mockImplementation(
                    () =>
                        new Promise((resolve) =>
                            setTimeout(
                                () =>
                                    resolve({
                                        survivor: { ...person },
                                        results: [
                                            { sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' },
                                        ],
                                    }),
                                50_000
                            )
                        )
                )
                void bound.mergePersons({
                    teamId: 1,
                    targetDistinctId: 'd1',
                    sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                    eventOps: ops({}, '$identify'),
                    eventUuid: 'event-uuid',
                    allowIdentifiedSources: false,
                    mergeMode: createDefaultSyncMergeMode(),
                    createdAtMs: 3_600_000,
                })
                await jest.advanceTimersByTimeAsync(0)

                const fold = bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
                const settled = fold.then(
                    () => 'folded' as const,
                    () => 'failed' as const
                )
                await jest.advanceTimersByTimeAsync(60_000)
                expect(await settled).toBe('folded')
            } finally {
                jest.useRealTimers()
            }
        })

        it('a flush exhausts its rounds rather than acking over lanes a merge never released', async () => {
            // Degraded to a return, the rounds guard would let the batch
            // commit offsets over segments that exist only in this process.
            // The driving case is a fence present at every capture but
            // released at every wait, the timing a merge storm produces.
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            ;(store as any).fences.set('1:7', new Set([new Promise<void>(() => {})]))
            ;(store as any).awaitFences = () => Promise.resolve()

            await expect(bound.flush()).rejects.toThrow(/flush cannot complete/)
            expect((store as any).entries.get('1:7').segments).toHaveLength(1)
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
            })

            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                eventUuid: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })

            // With nowhere to repoint, the id must at least stop naming the
            // destroyed person.
            expect((store as any).memo.resolutionOf('1:anon-1') !== undefined).toBe(false)
            expect((store as any).memo.hasBaseline('1:9')).toBe(false)
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
            eventUuid: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })

        it('a late fill-only response does not roll back a drained lane\u2019s projection', async () => {
            // Batch 1 holds the projection alive by resolution reference
            // while batch 0 retires the lane, leaving a projection with no
            // lane behind it: exactly when a stale install slips past an
            // entries-based guard.
            const bound1 = store.forBatch(1)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound1.fetchForUpdate(1, 'd1')

            const bound0 = store.forBatch(0)
            await bound0.applyEventOps(person, ops({ $set: { flag: 'on' } }), 'd1')
            await bound0.flush()
            store.releaseBatch(0)
            expect((store as any).entries.has('1:7')).toBe(false)

            // A prefetch issued before the flush delivers its stale snapshot
            // now. Installing it would give batch 1 a baseline without `flag`,
            // and a revert-shaped $set would classify no-change.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd2', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, properties: { plan: 'free' } } as never)
            await store.prefetchPersons([{ teamId: 1, distinctId: 'd2', batchId: 1 }])

            const seen = await bound1.fetchForUpdate(1, 'd1')
            expect(seen?.properties).toEqual(expect.objectContaining({ flag: 'on' }))
        })

        it('the update read class does not serve an identity-backed baseline', async () => {
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

        it('a leader read vouches for the person under every id that names it', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'd1', person },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, properties: { plan: 'leader' } } as never)
            await bound.fetchForUpdate(1, 'd1')

            // A sibling id resolves through identity to the same person.
            repository.resolvePersonsByDistinctIds.mockResolvedValueOnce([
                { teamId: 1, distinctId: 'd2', person },
            ] as never)
            await bound.fetchForChecking(1, 'd2')

            // Provenance describes the state, and the state is shared: d2's
            // update read is entitled to the leader document d1 paid for.
            const seen = await bound.fetchForUpdate(1, 'd2')
            expect(seen?.properties).toEqual({ plan: 'leader' })
            expect(repository.fetchPersonById).toHaveBeenCalledTimes(1)
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

        it('a replayed merged verdict cannot mark the survivor dead through the memo', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: person,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
            })
            // The survivor is alive at the leader; the refresh reads it.
            repository.fetchPersonById.mockResolvedValue(person as never)
            await bound.mergePersons(mergeReq())
            // The first call repointed anon-1 to the survivor. A replay of
            // the same verdict now resolves anon-1 to the survivor itself;
            // claiming that key dead would strip the survivor's projection
            // and discard the ops its live lane still holds.
            await bound.applyEventOps(person, ops({ $set: { alive: 'yes' } }), 'd1')
            await bound.mergePersons(mergeReq())

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
                        releases.push(() => resolve({ survivor: person, results: [] }))
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

        it('an abandoned batch sheds the unwritten lane it alone was keeping', async () => {
            // The shadow valve: a failed shadow flush cannot fail the batch,
            // so the release must not retain the lanes it left behind. The
            // counter is the instrument the ledger names for reading a
            // shed-correlated divergence spike.
            const shedBefore = await counterTotal(personhogStoreShadowShedCounter)
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')

            store.abandonBatch(0)

            expect((store as any).entries.has('1:7')).toBe(false)
            expect((store as any).memo.baselineCount).toBe(0)
            expect(await counterTotal(personhogStoreShadowShedCounter)).toBe(shedBefore + 1)
        })

        it('an abandoned in-flight lane is left to its write, then shed when the write fails', async () => {
            const bound0 = store.forBatch(0)
            await bound0.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            // Batch 1's merge fences the person; its pre-merge lane write
            // hangs holding the claim across batch 0's release.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            let failWrite: (e: Error) => void = () => {}
            repository.updatePersonProperties.mockImplementation(
                (() =>
                    new Promise((_, reject) => {
                        failWrite = reject
                    })) as never
            )
            repository.mergePersons = jest.fn().mockImplementation(() => new Promise(() => {}))
            const merging = store
                .forBatch(1)
                .mergePersons({
                    teamId: 1,
                    targetDistinctId: 'd1',
                    sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                    eventOps: ops({}, '$identify'),
                    eventUuid: 'event-uuid',
                    allowIdentifiedSources: false,
                    mergeMode: createDefaultSyncMergeMode(),
                    createdAtMs: 3_600_000,
                })
                .catch((error) => error)
            while (!(store as any).entries.get('1:7')?.inFlight) {
                await new Promise((resolve) => setImmediate(resolve))
            }

            store.abandonBatch(0)

            // The write owns the lane; abandon must not zero segments under
            // its pass.
            expect((store as any).entries.get('1:7').segments).toHaveLength(1)

            failWrite(new Error('identity down'))
            await merging

            // The failed settle sheds what nothing references, so the entry
            // does not persist as ownerless retry work no abandon revisits.
            expect((store as any).entries.has('1:7')).toBe(false)
        })

        it('a live batch folding onto an abandoned lane cancels the pending shed', async () => {
            // The settle-shed exists for ownerless entries; a live batch
            // referencing the entry again owns it, and the settle's own
            // reference check must skip the shed rather than discard the
            // ops that batch is folding.
            const bound0 = store.forBatch(0)
            await bound0.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            let failWrite: (e: Error) => void = () => {}
            repository.updatePersonProperties.mockImplementation(
                (() =>
                    new Promise((_, reject) => {
                        failWrite = reject
                    })) as never
            )
            repository.mergePersons = jest.fn().mockImplementation(() => new Promise(() => {}))
            const merging = store
                .forBatch(1)
                .mergePersons({
                    teamId: 1,
                    targetDistinctId: 'd1',
                    sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                    eventOps: ops({}, '$identify'),
                    eventUuid: 'event-uuid',
                    allowIdentifiedSources: false,
                    mergeMode: createDefaultSyncMergeMode(),
                    createdAtMs: 3_600_000,
                })
                .catch((error) => error)
            while (!(store as any).entries.get('1:7')?.inFlight) {
                await new Promise((resolve) => setImmediate(resolve))
            }
            store.abandonBatch(0)

            // The reference a fold records synchronously; the fold itself
            // would wait out the merge's fence first, which is beside the
            // point here — the claim being pinned is that a live reference
            // cancels the pending shed.
            ;(store as any).referenceEntry(2, '1:7')

            failWrite(new Error('identity down'))
            await merging

            const entry = (store as any).entries.get('1:7')
            expect(entry.segments.length).toBeGreaterThan(0)
        })

        it('an abandoned batch keeps segments a still-open batch references', async () => {
            const bound0 = store.forBatch(0)
            await bound0.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            const bound1 = store.forBatch(1)
            await bound1.applyEventOps(person, ops({ $set: { b: '2' } }), 'd1')

            store.abandonBatch(0)

            expect((store as any).entries.get('1:7').segments.length).toBeGreaterThan(0)
        })

        it('shutdown accepts a drained lane a batch has not released yet', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            await bound.flush()

            // The entry outlives its ops until the batch releases it. Reading
            // that as unwritten work would refuse a shutdown with nothing
            // left to write.
            await expect(store.shutdown()).resolves.toBeUndefined()
        })

        it('shutdown fails loudly while lanes still hold unwritten ops', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            await expect(store.shutdown()).rejects.toThrow(/unwritten ops/)
        })
    })

    describe('review regressions', () => {
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
                            })
                    })
            )
            await bound.applyEventOps(dead, ops({ $set: { a: '1' } }), 'anon-1')

            const merging = bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                eventUuid: 'event-uuid',
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

            // `local` was written before the merge, so the document the saga
            // folds already holds it and hands it back on the survivor —
            // where the old carry path replayed it locally instead.
            repository.mergePersons = jest.fn().mockResolvedValue({
                // The fold sealed the pre-merge write, so its version sits
                // above the write's answer — a survivor below it is a replay.
                survivor: { ...person, version: 4, properties: { plan: 'free', fromSource: 'merged', local: 'mine' } },
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
            })
            // The refresh reads the leader, which is at or past the fold.
            repository.fetchPersonById.mockResolvedValue({
                ...person,
                version: 5,
                properties: { plan: 'free', fromSource: 'merged', local: 'mine' },
            } as never)
            await bound.mergePersons({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventOps: ops({}, '$identify'),
                eventUuid: 'event-uuid',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })

            // The merge folded `fromSource` in, which no local projection
            // could know; the batch's own unwritten `local` still stands.
            const seen = await bound.fetchForUpdate(1, 'd1')
            expect(seen?.properties).toEqual({ plan: 'free', fromSource: 'merged', local: 'mine' })
        })

        it('releases the lanes behind a write that failed', async () => {
            const bound = store.forBatch(0)
            // A throw on one lane must not leave another marked in flight,
            // which every later pass would skip forever.
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { a: '1' } }), 'anon-1')
            await bound.applyEventOps({ ...person, id: '10' }, ops({ $set: { b: '2' } }), 'anon-2')
            repository.updatePersonProperties.mockRejectedValue(new Error('leader unavailable') as never)

            await expect(bound.flush()).rejects.toThrow('leader unavailable')

            expect((store as any).entries.get('1:10').inFlight).toBe(false)
            // And the next pass can actually take them again.
            repository.updatePersonProperties.mockResolvedValue({ person, updated: true } as never)
            await bound.flush()
            const written = repository.updatePersonProperties.mock.calls.map(([request]) => request.personId)
            expect(written).toEqual(expect.arrayContaining(['9', '10']))
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

        // The extra pays a resolve to learn which person it names; the
        // state it then sees is the shared view, pending ops included.
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd2', person }] as never)
        repository.fetchPersonById.mockResolvedValue({ ...person } as never)
        const viaD2 = await bound.fetchForUpdate(1, 'd2')
        expect(viaD2?.properties).toMatchObject({ a: '1' })
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
        // What the leader answered, not what was sent: the caller reads the
        // applied document back, scalars included.
        expect(updated).toEqual({
            ...person,
            version: 2,
            properties: { plan: 'pro' },
            is_identified: true,
            last_seen_at: DateTime.fromMillis(7_200_000, { zone: 'utc' }),
        })
        expect(messages).toEqual([])
    })

    it('refuses a diff update carrying fields the RPC cannot express', async () => {
        const bound = store.forBatch(0)
        await expect(
            bound.updatePersonWithPropertiesDiffForUpdate(person, {}, [], { created_at: person.created_at }, 'd1')
        ).rejects.toThrow(PersonhogUnsupportedFieldError)
        expect(repository.updatePersonProperties).not.toHaveBeenCalled()
    })

    describe('writing lanes before the merge', () => {
        const request = () => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
            eventOps: ops({}, '$identify'),
            eventUuid: 'event-uuid',
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        })
        const sagaOpId = (): string => mergeOpIdFromRequest(1, 'event-uuid', ['anon-1'], 10_000)
        // A function, not a value: `person` is assigned in beforeEach, so a
        // literal here would capture undefined and hand back a survivor with
        // no id.
        const merged = (): Record<string, unknown> => ({
            // The fold bumps the survivor's version past every prior read,
            // so a genuine merge survivor always clears the version guard;
            // only a replayed verdict from an earlier merge arrives below it.
            survivor: { ...person, version: 7, properties: { plan: 'merged' } },
            results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' }],
        })

        it('a lane opened by a sibling id still reaches the leader before its person dies', async () => {
            const bound = store.forBatch(0)
            // The event that opens the lane arrives on 'sibling', which the
            // merge below never names. Same person either way.
            await bound.applyEventOps(person, ops({ $set: { kept: 'yes' } }), 'sibling')
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, id: '9', properties: { plan: 'merged' } },
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '7' }],
            } as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person },
            ] as never)

            await bound.mergePersons(request())
            await bound.flush()

            // Postgres reaches the same pending update through any of the
            // person's distinct ids, so it folds these into the survivor.
            const sent = repository.updatePersonProperties.mock.calls.map((c: any[]) => c[0].setProperties)
            expect(sent).toContainEqual({ kept: 'yes' })
        })

        it('replays a retained lane over the survivor the saga returned', async () => {
            // The own-fence branch leaves the lane in place, so the batch's
            // read-your-write view is the merged document with those ops on
            // top. Installing the survivor alone would hide the batch's own
            // earlier writes from its later events.
            repository.updatePersonProperties.mockRejectedValue(
                new PersonhogFencedError('PERSON_MERGING', '7', sagaOpId()) as never
            )
            repository.mergePersons = jest.fn().mockResolvedValue(merged())
            repository.fetchPersonById.mockResolvedValue({
                ...person,
                version: 7,
                properties: { plan: 'merged' },
            } as never)
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { mine: 'kept' } }), 'd1')

            await bound.mergePersons(request())

            const projected = (store as any).memo.viewOfPerson('1:7')
            expect(projected.properties).toEqual({ plan: 'merged', mine: 'kept' })
        })

        it('releases the resolutions of a person only a stale belief named', async () => {
            // The memo believed anon-1 was person 5; the merge's own resolve
            // answers 9 and the saga destroys it. Without the captured
            // belief, 5's edge would survive and later events would read a
            // person the merge folded away.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '5' } },
                { teamId: 1, distinctId: 'anon-2', person: { ...person, id: '5' } },
            ] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person, id: '5' } as never)
            const bound = store.forBatch(0)
            await bound.fetchForUpdate(1, 'anon-1')
            await bound.fetchForUpdate(1, 'anon-2')
            expect((store as any).memo.resolutionOf('1:anon-2')).toBe('1:5')

            // The merge's own resolve answers 9 and the saga destroys it. The
            // sibling id anon-2 is never named by the request, so only the
            // captured belief can connect it to a person that is now gone.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            repository.mergePersons = jest.fn().mockResolvedValue(merged())

            await bound.mergePersons(request())

            expect((store as any).memo.resolutionOf('1:anon-2')).not.toBe('1:5')
        })

        it('does not let a concurrent flush resolve over a lane a merge is writing', async () => {
            // The merge claims the lane and writes it. A flush that skipped
            // the claim instead of waiting would resolve — and its batch ack
            // — while those ops were still on the wire.
            let releaseWrite: () => void = () => {}
            repository.updatePersonProperties.mockImplementation((() => {
                return new Promise((resolve) => {
                    releaseWrite = () => resolve({ person, updated: true })
                })
            }) as never)
            repository.mergePersons = jest.fn().mockResolvedValue(merged())
            const boundA = store.forBatch(0)
            const boundB = store.forBatch(1)
            await boundA.applyEventOps(person, ops({ $set: { plan: 'buffered' } }), 'd1')

            const merging = boundB.mergePersons(request())
            await new Promise((resolve) => setTimeout(resolve, 0))

            let flushSettled = false
            const flushing = boundA.flush().then(() => {
                flushSettled = true
            })
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(flushSettled).toBe(false)
            // One entry, one writer: the flush must wait the merge's write
            // out, not start a second one over the same segments, which would
            // leave two truncations racing over one lane.
            const writesFor7 = () =>
                repository.updatePersonProperties.mock.calls.filter(([call]) => call.personId === '7')
            expect(writesFor7()).toHaveLength(1)

            releaseWrite()
            await merging
            await flushing
            expect(flushSettled).toBe(true)
            expect(writesFor7()).toHaveLength(1)
        })

        it('waits for a write another merge claimed before folding around it', async () => {
            // Two merges overlap on one person. The first claims the lane and
            // its write is on the wire; without arming the promise the second
            // reads, it would fold a document the first is still writing.
            let releaseWrite: () => void = () => {}
            repository.updatePersonProperties.mockImplementation((() => {
                return new Promise((resolve) => {
                    releaseWrite = () => resolve({ person, updated: true })
                })
            }) as never)
            repository.mergePersons = jest.fn().mockResolvedValue(merged())
            const boundA = store.forBatch(0)
            const boundB = store.forBatch(1)
            await boundA.applyEventOps(person, ops({ $set: { plan: 'buffered' } }), 'd1')

            const first = boundA.mergePersons(request())
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)

            const second = boundB.mergePersons(request())
            await new Promise((resolve) => setTimeout(resolve, 0))
            // The second merge is parked on the first's write, so its request
            // has not gone out.
            expect(repository.mergePersons).not.toHaveBeenCalled()

            releaseWrite()
            await first
            await second
            expect(repository.mergePersons).toHaveBeenCalled()
        })

        it('lands the buffered writes before the merge request goes out', async () => {
            // The saga folds documents as it finds them, so anything still
            // buffered here would land after the fold and beat values the
            // merge rules say the target keeps.
            const order: string[] = []
            repository.updatePersonProperties.mockImplementation((() => {
                order.push('write')
                return Promise.resolve({ person, updated: true })
            }) as never)
            repository.mergePersons = jest.fn().mockImplementation(() => {
                order.push('merge')
                return Promise.resolve(merged())
            })
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { plan: 'buffered' } }), 'd1')

            await bound.mergePersons(request())

            expect(order).toEqual(['write', 'merge'])
        })

        it('merges anyway when the fence holding a lane belongs to this saga', async () => {
            // A previous delivery parked mid-saga and still holds the fence.
            // Only a retry under the same op id resumes it, and that retry is
            // the merge below — so the lane waits rather than blocking it.
            personhogStoreFenceCounter.reset()
            repository.updatePersonProperties.mockRejectedValue(
                new PersonhogFencedError('PERSON_MERGING', '7', sagaOpId()) as never
            )
            repository.mergePersons = jest.fn().mockResolvedValue(merged())
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { plan: 'buffered' } }), 'd1')

            await bound.mergePersons(request())

            expect(repository.mergePersons).toHaveBeenCalledTimes(1)
            expect((store as any).entries.get('1:7')?.segments ?? []).toHaveLength(1)
            const outcomes = (await personhogStoreFenceCounter.get()).values.map((v) => v.labels.outcome)
            expect(outcomes).toContain('own_saga_holds_person')
        })

        it('a same-event sibling fence drops the merge like a foreign one, labeled as ours', async () => {
            // The fence is our own event's, under an op id this delivery
            // cannot reconstruct. Proceeding would fold the person with its
            // lane unwritten and deferring could loop forever, so it takes
            // the claim-race drop with the sibling attribution.
            personhogStoreFenceCounter.reset()
            repository.updatePersonProperties.mockRejectedValue(
                new PersonhogFencedError('PERSON_MERGING', '7', 'an-underivable-op-id', 'event-uuid') as never
            )
            repository.mergePersons = jest.fn().mockResolvedValue(merged())
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { plan: 'buffered' } }), 'd1')

            await expect(bound.mergePersons(request())).rejects.toBeInstanceOf(PersonClaimedByLifecycleOpError)

            expect(repository.mergePersons).not.toHaveBeenCalled()
            const outcomes = (await personhogStoreFenceCounter.get()).values.map((v) => v.labels.outcome)
            expect(outcomes).toContain('sibling_op_holds_person')
            expect(outcomes).not.toContain('foreign_lifecycle_op')
        })

        it('a fence that is ours by op id is own even when the creator also matches', async () => {
            // The common production shape: an earlier delivery's fence under
            // the base derivation carries our creator too. Ownership must win
            // over the sibling classification, or every genuine own fence
            // would defer instead of driving its operation forward.
            personhogStoreFenceCounter.reset()
            repository.updatePersonProperties.mockRejectedValue(
                new PersonhogFencedError('PERSON_MERGING', '7', sagaOpId(), 'event-uuid') as never
            )
            repository.mergePersons = jest.fn().mockResolvedValue(merged())
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { plan: 'buffered' } }), 'd1')

            await bound.mergePersons(request())

            expect(repository.mergePersons).toHaveBeenCalledTimes(1)
            const outcomes = (await personhogStoreFenceCounter.get()).values.map((v) => v.labels.outcome)
            expect(outcomes).toContain('own_saga_holds_person')
            expect(outcomes).not.toContain('sibling_op_deferred')
        })

        it("a fence naming another event's creator stays foreign", async () => {
            // Carrying a creator is not enough; only this request's own
            // event may drive the fenced op forward.
            repository.updatePersonProperties.mockRejectedValue(
                new PersonhogFencedError('PERSON_MERGING', '7', 'a-different-op', 'another-event-uuid') as never
            )
            repository.mergePersons = jest.fn().mockResolvedValue(merged())
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { plan: 'buffered' } }), 'd1')

            await expect(bound.mergePersons(request())).rejects.toBeInstanceOf(PersonClaimedByLifecycleOpError)
            expect(repository.mergePersons).not.toHaveBeenCalled()
        })

        it('a foreign lifecycle op drops the merge as a claim race', async () => {
            // Somebody else is rewriting this person. Merging around them
            // would fold a document being changed underneath us, so the batch
            // fails and redelivery retries once they are done.
            repository.updatePersonProperties.mockRejectedValue(
                new PersonhogFencedError('PERSON_DELETING', '7', 'a-different-op') as never
            )
            repository.mergePersons = jest.fn().mockResolvedValue(merged())
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { plan: 'buffered' } }), 'd1')

            // Surfaced as the claim error both backends share, so the merge
            // service drops the merge with a race warning instead of acking
            // it silently or failing a batch that would only contend again.
            await expect(bound.mergePersons(request())).rejects.toBeInstanceOf(PersonClaimedByLifecycleOpError)
            expect(repository.mergePersons).not.toHaveBeenCalled()
        })

        it('redirects a vanished person without waiting on its own fence', async () => {
            // The pre-merge write finds the person already merged away. The
            // redirect must not park on the fence this very merge installed,
            // which nothing but this merge can release.
            repository.updatePersonProperties.mockImplementation(((call: { personId: string }) =>
                call.personId === '7'
                    ? Promise.reject(new NoRowsUpdatedError('merged away'))
                    : Promise.resolve({ person, updated: true })) as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: { ...person, id: '12' } },
            ] as never)
            repository.mergePersons = jest.fn().mockResolvedValue(merged())
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { plan: 'buffered' } }), 'd1')

            personhogStoreFenceCounter.reset()
            await bound.mergePersons(request())

            const written = repository.updatePersonProperties.mock.calls.map(([call]) => call.personId)
            expect(written).toContain('12')
            expect(repository.mergePersons).toHaveBeenCalledTimes(1)
            // With the guard removed the write would still happen once the
            // fence wait expires, so no recorded wait is the only
            // observable difference.
            expect((await personhogStoreFenceCounter.get()).values).toEqual([])
        })

        it('keeps a person fenced until the last merge holding it releases', async () => {
            // A person can be one merge's source and another's target.
            // Tracking a single holder lets whichever releases first unfence a
            // person the other is still rewriting.
            let releaseSlow: () => void = () => {}
            const slowMerging = new Promise<void>((resolve) => {
                releaseSlow = resolve
            })
            repository.mergePersons = jest
                .fn()
                .mockImplementationOnce(() => slowMerging.then(() => merged()))
                .mockImplementationOnce(() => Promise.resolve(merged()))
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            const bound = store.forBatch(0)
            // Resolved, not folded: a lane would make the second merge defer
            // behind the first and fail before it could release anything.
            await bound.fetchForUpdate(1, 'd1')

            const slow = bound.mergePersons(request())
            const quick = bound.mergePersons({ ...request(), eventUuid: 'other-event' })
            await quick

            // The quick merge has released. The slow one still holds the
            // person, so a fold must not proceed.
            let folded = false
            const fold = bound.applyEventOps(person, ops({ $set: { late: '1' } }), 'd1').then(() => {
                folded = true
            })
            await new Promise((resolve) => setImmediate(resolve))
            expect(folded).toBe(false)

            releaseSlow()
            await slow
            await fold
            expect(folded).toBe(true)
        })

        it('waits again when the merge it waited out handed the id to a person another merge holds', async () => {
            // A fold parks on one merge, which repoints the id to a person a
            // second merge already holds. Resuming against the original key
            // would fold into that second request, where reconcile sweeps the
            // ops into a discard they do not belong to.
            repository.resolvePersonsByDistinctIds.mockImplementation(((keys: { distinctId: string }[]) =>
                Promise.resolve(
                    keys.map(({ distinctId }) => ({
                        teamId: 1,
                        distinctId,
                        person: {
                            ...person,
                            id: { other: '9', 'other-src': '11' }[distinctId] ?? '7',
                        },
                    }))
                )) as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)

            let releaseSecond: () => void = () => {}
            const secondRunning = new Promise<void>((resolve) => {
                releaseSecond = resolve
            })
            let releaseFirst: () => void = () => {}
            const firstRunning = new Promise<void>((resolve) => {
                releaseFirst = resolve
            })
            repository.mergePersons = jest
                .fn()
                .mockImplementationOnce(() => secondRunning.then(() => merged()))
                .mockImplementationOnce(() =>
                    firstRunning.then(() => ({
                        // Hands d1 to person 9, which the first merge holds.
                        survivor: { ...person, id: '9' },
                        results: [{ sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '7' }],
                    }))
                )
            const bound = store.forBatch(0)

            // Holds 9 and 11 only: its source must not name person 7, or it
            // would satisfy the fold's wait for the wrong reason.
            const holdingNine = bound.mergePersons({
                ...request(),
                eventUuid: 'hold-nine',
                targetDistinctId: 'other',
                sources: [{ distinctId: 'other-src', eventUuid: 'hold-nine-uuid' }],
            })
            const repointing = bound.mergePersons(request())
            await new Promise((resolve) => setImmediate(resolve))

            let folded = false
            const fold = bound.applyEventOps(person, ops({ $set: { late: '1' } }), 'd1').then(() => {
                folded = true
            })

            releaseFirst()
            await repointing
            await new Promise((resolve) => setImmediate(resolve))
            // d1 now names person 9, and person 9 is still held.
            expect(folded).toBe(false)

            releaseSecond()
            await holdingNine
            await fold
            expect(folded).toBe(true)
        })

        it('fails rather than merging around a lane that is mid-redirect', async () => {
            // Between a direct write finding its person gone and the redirect
            // registering, the lane is in flight with nothing a merge can wait
            // on. Skipping it would fold a person whose buffered ops are
            // unaccounted for, so the merge fails instead.
            let releaseResolve: () => void = () => {}
            const resolving = new Promise<void>((resolve) => {
                releaseResolve = resolve
            })
            let announceRedirect: () => void = () => {}
            const reachedRedirect = new Promise<void>((resolve) => {
                announceRedirect = resolve
            })
            // Only the redirect's single-key resolve parks; the merge's own
            // resolve of its named ids must still answer.
            repository.resolvePersonsByDistinctIds.mockImplementation(((keys: { distinctId: string }[]) =>
                keys.length === 1
                    ? (announceRedirect(),
                      resolving.then(() => [{ teamId: 1, distinctId: 'd1', person: { ...person, id: '9' } }]))
                    : Promise.resolve(
                          keys.map(({ distinctId }) => ({ teamId: 1, distinctId, person: { ...person } }))
                      )) as never)
            repository.updatePersonProperties.mockRejectedValue(new NoRowsUpdatedError('merged away') as never)
            repository.mergePersons = jest.fn().mockResolvedValue(merged())

            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { plan: 'buffered' } }), 'd1')
            // Starts the flush; its direct write fails and the redirect parks
            // on the resolve, leaving the lane in the invisible window.
            const flushing = bound.flush()
            // Waits for the redirect to actually reach its resolve rather
            // than for a fixed number of ticks: under load the flush can
            // still be short of that window when a tick count expires, and
            // the merge then sails past a lane that is not yet in flight.
            await reachedRedirect

            await expect(bound.mergePersons(request())).rejects.toBeInstanceOf(PersonMergeCallFailedError)
            expect(repository.mergePersons).not.toHaveBeenCalled()

            releaseResolve()
            await flushing.catch(() => undefined)
        })

        it('carries a stranded lane to the survivor at full strength, deletions included', async () => {
            // Another pod merged away a person this one holds ops for.
            // Postgres carries pending sets and unsets across unchanged, so
            // weakening them here would lose a deletion the customer asked
            // for and diverge from that backend.
            repository.resolvePersonsByDistinctIds.mockImplementation(((keys: { distinctId: string }[]) =>
                Promise.resolve(
                    keys.map(({ distinctId }) => ({ teamId: 1, distinctId, person: { ...person, id: '7' } }))
                )) as never)
            const writes: { personId: string; set: unknown; setOnce: unknown; unset: unknown }[] = []
            repository.updatePersonProperties.mockImplementation(((call: {
                personId: string
                setProperties: unknown
                setOnceProperties: unknown
                unsetProperties: unknown
            }) => {
                if (call.personId === '9') {
                    return Promise.reject(new NoRowsUpdatedError('merged away'))
                }
                writes.push({
                    personId: call.personId,
                    set: call.setProperties,
                    setOnce: call.setOnceProperties,
                    unset: call.unsetProperties,
                })
                return Promise.resolve({ person, updated: true })
            }) as never)
            repository.mergePersons = jest.fn().mockResolvedValue(merged())

            const bound = store.forBatch(0)
            await bound.applyEventOps(
                { ...person, id: '9' },
                ops({ $set: { plan: 'ours' }, $unset: ['stale'] }),
                'anon-1'
            )
            await bound.mergePersons(request())

            const survivorWrite = writes.find((write) => write.personId === '7')
            expect(survivorWrite?.set).toEqual({ plan: 'ours' })
            expect(survivorWrite?.unset).toEqual(['stale'])
            expect(survivorWrite?.setOnce).toEqual({})
        })

        it('fails the merge when the persons it must hold cannot be resolved', async () => {
            // Resolution decides which persons are held and written before
            // the fold, so degrading to the memo leaves a person the saga
            // folds neither held nor written. The resolve retries internally,
            // so reaching here means identity is down.
            repository.resolvePersonsByDistinctIds.mockRejectedValue(new Error('identity unavailable') as never)
            repository.mergePersons = jest.fn().mockResolvedValue(merged())
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { plan: 'buffered' } }), 'd1')

            await expect(bound.mergePersons(request())).rejects.toBeInstanceOf(PersonMergeCallFailedError)
            expect(repository.mergePersons).not.toHaveBeenCalled()
        })

        it('fails the merge when a foreign fence defers a pre-merge write', async () => {
            // Reading a deferral as success would send the merge with this
            // lane still buffered, folding a person whose changes have not
            // landed. Reachable through the gap between claiming a lane and
            // reaching a concurrency slot, which one slot makes deterministic.
            const narrowStore = new PersonhogPersonsStore(repository, { maxConcurrentUpdates: 1 })
            const bound = narrowStore.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            await bound.applyEventOps({ ...person, id: '9' }, ops({ $set: { b: '2' } }), 'anon-1')

            // Holds the first write open so the second is still queued when
            // the foreign merge arrives.
            let releaseFirstWrite: () => void = () => {}
            const firstWriting = new Promise<void>((resolve) => {
                releaseFirstWrite = resolve
            })
            let started = 0
            repository.updatePersonProperties.mockImplementation(((call: { personId: string }) => {
                started += 1
                return started === 1
                    ? firstWriting.then(() => ({ person: { ...person, id: call.personId }, updated: true }))
                    : Promise.resolve({ person: { ...person, id: call.personId }, updated: true })
            }) as never)
            repository.mergePersons = jest.fn().mockResolvedValue(merged())

            const merging = bound.mergePersons(request())
            await new Promise((resolve) => setImmediate(resolve))

            // A second merge fences a person whose lane the first has claimed
            // but not written. The handler is attached here rather than after
            // the await below, since a rejection nobody is listening for takes
            // the process down.
            const foreign = bound
                .mergePersons({
                    ...request(),
                    eventUuid: 'foreign-event',
                    targetDistinctId: 'anon-1',
                    sources: [{ distinctId: 'anon-2', eventUuid: 'foreign-uuid' }],
                })
                .catch(() => undefined)
            releaseFirstWrite()

            await expect(merging).rejects.toBeInstanceOf(PersonMergeCallFailedError)
            await foreign
        })
    })
})
