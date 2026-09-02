import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import { PersonhogFencedError, PersonhogPropertiesSizeError } from '~/common/personhog/persons'
import { NoRowsUpdatedError } from '~/common/utils/utils'
import { InternalPerson } from '~/types'

import { PersonMergeCallFailedError, createDefaultSyncMergeMode } from './person-merge-types'
import { EventOps, extractEventOps } from './person-update'
import { mergeOpIdFromRequest } from './person-uuid'
import {
    PersonhogPersonsStore,
    PersonhogUnsupportedFieldError,
    personhogStoreFlushCounter,
    personhogStoreMergeCacheCounter,
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

    describe('every lane reaches the leader, carrying the event force flag', () => {
        // Classification moved server-side: the leader decides whether a
        // filtered-only lane writes, so the store must send everything and
        // the force flag is what the leader classifies under.
        it('a filtered-only lane still writes, unforced', async () => {
            person.properties = { $browser: 'Firefox' }
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { $browser: 'Chrome' } }, 'pageview'), 'd1')
            await bound.flush()
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
            expect(repository.updatePersonProperties.mock.calls[0][0].forceUpdate).toBe(false)
        })

        it('a person event writes forced', async () => {
            person.properties = { $browser: 'Firefox' }
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { $browser: 'Chrome' } }, '$set'), 'd1')
            await bound.flush()
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
            expect(repository.updatePersonProperties.mock.calls[0][0].forceUpdate).toBe(true)
        })

        it('a forced event folded behind an unforced one forces the segment', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { plan: 'pro' } }, 'pageview'), 'd1')
            await bound.applyEventOps(person, ops({ $set: { $browser: 'Chrome' } }, '$set'), 'd1')
            await bound.flush()
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
            expect(repository.updatePersonProperties.mock.calls[0][0].forceUpdate).toBe(true)
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

    it('an update read does not trust a checking-read document', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([
            { teamId: 1, distinctId: 'd1', person: { ...person, version: 3, properties: { plan: 'lagged' } } },
        ] as never)
        repository.fetchPersonById.mockResolvedValue({ ...person, version: 5, properties: { plan: 'fresh' } } as never)
        const bound = store.forBatch(0)

        const checked = await bound.fetchForChecking(1, 'd1')
        expect(checked?.properties).toEqual({ plan: 'lagged' })
        expect(repository.fetchPersonById).not.toHaveBeenCalled()

        // The checking read installed identity's writer-lagged document; the
        // update path pays the leader read it skipped, the way the Postgres
        // store keeps its check cache out of the update path.
        const updated = await bound.fetchForUpdate(1, 'd1')
        expect(updated?.properties).toEqual({ plan: 'fresh' })
        expect(repository.fetchPersonById).toHaveBeenCalledTimes(1)

        // Upgraded once: the next update read serves the memo.
        await bound.fetchForUpdate(1, 'd1')
        expect(repository.fetchPersonById).toHaveBeenCalledTimes(1)
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

        it('any other failed call fails the batch and keeps the batch view', async () => {
            // A semantic refusal from a later saga step (a parked op) and a
            // transport failure both redeliver rather than settle; stale
            // edges heal through the tombstone redirect, so nothing is
            // invalidated.
            const refuse = (code: Code, metadata?: Headers) => {
                repository.mergePersons = jest
                    .fn()
                    .mockRejectedValue(new ConnectError('refused after the flip', code, metadata))
            }

            refuse(Code.FailedPrecondition, new Headers({ 'x-semantic-refusal': 'release-unverified' }))
            let bound = store.forBatch(0)
            await bound.fetchForUpdate(1, 'd1')
            await expect(bound.mergePersons(mergeRequest())).rejects.toBeInstanceOf(PersonMergeCallFailedError)
            expect((store as any).memo.resolutionOf('1:d1')).toBeNull()

            refuse(Code.Unavailable)
            bound = store.forBatch(1)
            await expect(bound.mergePersons(mergeRequest())).rejects.toBeInstanceOf(PersonMergeCallFailedError)
            expect((store as any).memo.resolutionOf('1:d1')).toBeNull()
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

        it('a conflict verdict passes through in one call, unsalted', async () => {
            // The saga no longer records claim conflicts, so a plain retry
            // under the same op id re-runs fresh; the store neither salts
            // nor retries, and the caller's settled gate redelivers.
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: null,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'skipped_conflict', settled: false }],
            })
            const bound = store.forBatch(0)

            const result = await bound.mergePersons(mergeRequest())

            expect(result.results[0]?.outcome).toBe('skipped_conflict')
            expect(result.results[0]?.settled).toBe(false)
            expect(repository.mergePersons).toHaveBeenCalledTimes(1)
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

    it('drops a size-rejected segment from the lane rather than retrying it forever', async () => {
        repository.updatePersonProperties.mockRejectedValue(new PersonhogPropertiesSizeError('too big', 1, '7'))
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

        it('an aborted fold drops the survivor baseline it may have moved past', async () => {
            const bound = store.forBatch(0)
            ;(store as any).memo.offerBaseline('1:7', { ...person, version: 3 })
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, version: 9 },
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9' },
                    { sourceDistinctId: 'anon-2', outcome: 'skipped_conflict' },
                ],
            })

            await bound.mergePersons(mergeReq())

            // The saga's partial folds and the aborted-writes delivery moved
            // the leader past the standing baseline despite the abort, so
            // the next reader re-reads instead of serving it.
            expect((store as any).memo.hasBaseline('1:7')).toBe(false)
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

        it('a direct diff answered with no document but an applied write drops the baseline', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)
            repository.fetchPersonById.mockResolvedValue({ ...person } as never)
            await bound.fetchForUpdate(1, 'd1')
            repository.updatePersonProperties.mockResolvedValueOnce({ person: null, updated: true } as never)

            await bound.updatePersonWithPropertiesDiffForUpdate(person, { plan: 'pro' }, [], {}, 'd1')

            // The write applied, so the pre-write baseline must not go on
            // serving; the next reader re-reads.
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

        it('a person gone from identity fails the flush to redeliver, releasing the id', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { k: 'A' } }), 'd1')
            expect((store as any).memo.resolutionOf('1:d1')).toBe('1:7')
            // The person is deleted rather than merged, so the redirect's
            // resolve answers nobody. Redelivery recreates through the
            // normal pipeline, as Postgres does; dropping here would lose
            // the ops.
            repository.updatePersonProperties.mockRejectedValue(new NoRowsUpdatedError('deleted') as never)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([] as never)

            await expect(bound.flush()).rejects.toThrow(/resolves to nobody/)

            expect((store as any).entries.get('1:7').segments).toHaveLength(1)
            // Released, so the redelivered events re-resolve rather than
            // folding onto the deleted person again.
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

        const memoOf = (): any => (store as any).memo

        it('a create that finds a person the leader has lost memoizes nothing', async () => {
            // The leader answers null only for a destroyed person; the
            // caller keeps identity's answer, and memoizing it would serve
            // the dead person for the rest of the batch.
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

        it('folds onto the person the memo names, not the caller’s stale copy', async () => {
            const bound = store.forBatch(0)
            const other = { ...person, id: '9' }
            // d1 belongs to 9 and its document was dropped, so the fold has
            // to read rather than trust the caller's copy of person 7.
            ;(store as any).memo.recordResolution(0, '1:d1', '1:9')
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'd1', person: other },
            ] as never)
            repository.fetchPersonById.mockResolvedValue(other as never)

            const [projected] = await bound.applyEventOps(person, ops({ $set: { late: 'op' } }), 'd1')

            // Folding onto person 7 would repoint d1 off 9 and onto a person
            // a merge left behind, and later events would compose on top.
            expect(projected.id).toBe('9')
            expect((store as any).memo.resolutionOf('1:d1')).toBe('1:9')
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
            // person really merged, so its id already reads the survivor, or
            // later events fold onto the destroyed person.
            expect((store as any).memo.resolutionOf('1:anon-1')).toBe('1:7')
        })

        it('a fold with an unsettled source aborts, whatever name carries it', async () => {
            const bound = store.forBatch(0)
            repository.resolvePersonsByDistinctIds.mockResolvedValue([
                { teamId: 1, distinctId: 'anon-1', person: { ...person, id: '9' } },
            ] as never)
            // An unsettled verdict under a name outside the conflict
            // vocabulary: a retry may change it, so executing the fold would
            // ack anon-2's event on an answer that is not final.
            repository.mergePersons = jest.fn().mockResolvedValue({
                survivor: { ...person, version: 7 },
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'merged', sourcePersonId: '9', settled: true },
                    { sourceDistinctId: 'anon-2', outcome: 'error', settled: false },
                ],
            })

            const result = await bound.mergePersons({
                ...mergeReq(),
                sources: [
                    { distinctId: 'anon-1', eventUuid: 'event-uuid' },
                    { distinctId: 'anon-2', eventUuid: 'event-uuid-2' },
                ],
            })

            expect(result.foldAborted).toBe('conflict')
            expect(result.survivor).toBeNull()
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

        it('a merge call failure fails the batch instead of acking', async () => {
            const bound = store.forBatch(0)
            repository.mergePersons = jest.fn().mockRejectedValue(new Error('transport closed') as never)

            await expect(bound.mergePersons(mergeReq())).rejects.toThrow(PersonMergeCallFailedError)
        })
    })

    describe('round-3 regressions', () => {
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

        it('derives a valid op uuid from any event uuid string', async () => {
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
                eventUuid: 'not-a-uuid-at-all',
                allowIdentifiedSources: false,
                mergeMode: createDefaultSyncMergeMode(),
                createdAtMs: 3_600_000,
            })

            // Event uuids are client-supplied and not always UUIDs; the wire
            // always carries a well-formed uuidv5 the saga can parse.
            expect(repository.mergePersons.mock.calls[0][0].opId).toMatch(
                /^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$/
            )
        })
    })

    describe('round-2 coverage', () => {
        it('a flush exhausts its rounds rather than acking over a lane whose writer never settles', async () => {
            // Degraded to a return, the rounds guard would let the batch
            // commit offsets over segments that exist only in this process.
            jest.useFakeTimers()
            try {
                const bound = store.forBatch(0)
                await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
                const entry = (store as any).entries.get('1:7')
                entry.inFlight = true
                entry.directWriteSettled = new Promise<void>(() => {})

                const flushing = bound.flush()
                const settled = flushing.then(
                    () => 'acked' as const,
                    (error: Error) => error.message
                )
                await jest.advanceTimersByTimeAsync(10_000)
                expect(await settled).toMatch(/flush cannot complete/)
                expect((store as any).entries.get('1:7').segments).toHaveLength(1)
            } finally {
                jest.useRealTimers()
            }
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

            await expect(bound.flush()).rejects.toThrow(/resolves to nobody/)

            const sets = (store as any).entries.get('1:7').segments.map((segment: EventOps) => segment.set)
            expect(sets).toContainEqual({ later: 'fold' })
            expect(sets).toContainEqual({ b: '2' })
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

        it('a resolve still naming the vanished person fails the flush to redeliver', async () => {
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            repository.updatePersonProperties.mockRejectedValue(new NoRowsUpdatedError('merged away') as never)
            // Structurally the mapping is repointed before the leader ever
            // answers a tombstone, so this shape is an anomaly; failing
            // keeps the ops and surfaces it rather than dropping.
            repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }] as never)

            await expect(bound.flush()).rejects.toThrow(/the same person/)
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
        await expect(bound.flush()).rejects.toThrow('merged away')
        expect((store as any).entries.get('1:7').segments).toHaveLength(1)
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

        beforeEach(() => {
            // The drain covers the persons the fresh resolve names.
            repository.resolvePersonsByDistinctIds.mockImplementation(((keys: { distinctId: string }[]) =>
                Promise.resolve(
                    keys.map(({ distinctId }) => ({ teamId: 1, distinctId, person: { ...person } }))
                )) as never)
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

        it('a drain bounce on a lifecycle fence does not stop the merge', async () => {
            // A lifecycle op holds the person, often this request's own from
            // an interrupted delivery. Calling the saga is what settles
            // either case, and the lane's ops land later via the redirect.
            personhogStoreMergeCacheCounter.reset()
            repository.updatePersonProperties.mockRejectedValue(
                new PersonhogFencedError('PERSON_MERGING', '7', sagaOpId()) as never
            )
            repository.mergePersons = jest.fn().mockResolvedValue(merged())
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { plan: 'buffered' } }), 'd1')

            await bound.mergePersons(request())

            expect(repository.mergePersons).toHaveBeenCalledTimes(1)
            expect((store as any).entries.get('1:7')?.segments ?? []).toHaveLength(1)
            const actions = (await personhogStoreMergeCacheCounter.get()).values.map((v) => v.labels.action)
            expect(actions).toContain('premerge_lane_fenced')
        })

        it('a lane mid-redirect does not stop the merge', async () => {
            // Between a direct write finding its person gone and the
            // redirect resolving, the lane is in flight. Its ops land on
            // the survivor through the redirect, so the merge proceeds
            // without them rather than failing the batch.
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

            await expect(bound.mergePersons(request())).resolves.toBeDefined()
            expect(repository.mergePersons).toHaveBeenCalledTimes(1)

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
            await bound.flush()

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
    })
})
