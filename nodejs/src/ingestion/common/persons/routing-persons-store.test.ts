import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import {
    personhogStoreShadowCompareFailedCounter,
    personhogStoreShadowComparedCounter,
    personhogStoreShadowCreateRetriesCounter,
    personhogStoreShadowDivergenceCounter,
    personhogStoreShadowErrorsCounter,
    personhogStoreShadowFoldHeldCounter,
    personhogStoreShadowMergeRedriveCounter,
    personhogStoreShadowSkipsCounter,
} from '~/common/persons/metrics'
import { logger } from '~/common/utils/logger'
import { defaultRetryConfig } from '~/common/utils/retries'
import { InternalPerson } from '~/types'

import { BatchWritingPersonsStore } from './batch-writing-person-store'
import { PersonMergeCallFailedError } from './person-merge-types'
import { EventOps } from './person-update'
import { PersonhogPersonsStore } from './personhog-persons-store'
import { MergePersonsResult, PersonsBackend, PersonsStore } from './persons-store'
import { RoutingPersonsStore, assertPersonsStoreModeConfig, parsePersonsStoreMode } from './routing-persons-store'

const mockShadowTimerStop = jest.fn()

jest.mock('~/common/persons/metrics', () => ({
    personhogStoreShadowErrorsCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowSkipsCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowDivergenceCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowComparedCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowCompareFailedCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowFoldRedriveCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowMergeRedriveCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowCreateRetriesCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowFoldHeldCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowDurationSeconds: {
        labels: jest.fn().mockReturnValue({ startTimer: jest.fn(() => mockShadowTimerStop) }),
    },
}))

const emptyMergeResult = (): MergePersonsResult => ({ survivor: null, results: [] })

/**
 * A complete, compile-checked PersonsStore mock: the annotation forces
 * every interface member to exist, so an interface change breaks this
 * factory at compile time instead of leaving stale mocks that only fail
 * when a newly routed method runs.
 *
 * The cover is PersonsStore only. Tests hand this to the personhog slot
 * through a cast, so a member PersonhogPersonsStore adds beyond the
 * interface is not checked here and would surface at runtime.
 */
function mockStore(backend: PersonsBackend = 'postgres'): jest.Mocked<PersonsStore> {
    return {
        backend,
        fetchForChecking: jest.fn().mockResolvedValue(null),
        fetchForUpdate: jest.fn().mockResolvedValue(null),
        createPerson: jest.fn().mockResolvedValue({ success: true }),
        applyEventOps: jest.fn().mockImplementation((person: InternalPerson) => Promise.resolve([person, []])),
        updatePersonWithPropertiesDiffForUpdate: jest.fn(),
        mergePersons: jest.fn().mockResolvedValue(emptyMergeResult()),
        personPropertiesSize: jest.fn().mockResolvedValue(0),
        shutdown: jest.fn().mockResolvedValue(undefined),
        prefetchPersons: jest.fn().mockResolvedValue(undefined),
        flush: jest.fn().mockResolvedValue([]),
        releaseBatch: jest.fn(),
        getFlushStats: jest.fn().mockReturnValue({ dirtyEntryCount: 0, referencedBatchCount: 0, cacheEntryCount: 0 }),
    }
}

describe('RoutingPersonsStore', () => {
    it.each([
        // Shadow's personhog calls never reach a caller, so an error a caller
        // sees during a shadow rollout came from Postgres and must say so.
        ['personhog' as const, 'personhog'],
        ['shadow' as const, 'postgres'],
    ])('reports the authoritative backend in %s mode', (mode, expected) => {
        const store = new RoutingPersonsStore(
            mockStore('postgres') as unknown as BatchWritingPersonsStore,
            mockStore('personhog') as unknown as PersonhogPersonsStore,
            mode
        )
        expect(store.backend).toBe(expected)
    })

    const person = (teamId: number, id = '1'): InternalPerson =>
        ({ id, uuid: `uuid-${id}`, team_id: teamId, properties: {}, is_identified: false }) as unknown as InternalPerson

    const ops: EventOps = {
        set: {},
        setOnce: {},
        unset: [],
        denied: false,
        shouldForceUpdate: false,
        eventName: '$set',
    } as unknown as EventOps

    const makeStores = () => {
        const pg = Object.assign(mockStore(), {
            landedUuid: jest.fn().mockReturnValue(undefined),
            // The Postgres fold lands by default, on the person the event read.
            foldEventOps: jest
                .fn()
                .mockImplementation((found: InternalPerson) => ({ result: [found, []], landedOn: found.uuid })),
        })
        // The Postgres flush runs the seal it is given ahead of each decision round; the mock runs it once.
        pg.flush.mockImplementation((seal?: (deciding: never[]) => void) => {
            seal?.([])
            return Promise.resolve([])
        })
        // The personhog store implements PersonsStore, so the same
        // compile-checked factory serves; the cast to the concrete class
        // is the constructor's requirement, not an escape from checking.
        const personhogMock = Object.assign(mockStore(), {
            abandonBatch: jest.fn(),
            holdEventOps: jest.fn(),
            hasHeldOps: jest.fn().mockReturnValue(false),
            sealDecided: jest.fn(),
            applyEventOpsNow: jest.fn().mockReturnValue(false),
            applyEventOpsAsOwnSegment: jest
                .fn()
                .mockImplementation((found: InternalPerson) => Promise.resolve([found, []])),
        })
        const personhog = personhogMock as unknown as PersonhogPersonsStore
        return { pg, personhogMock, personhog }
    }

    const makeStore = (stores: ReturnType<typeof makeStores>, mode: 'personhog' | 'shadow') =>
        new RoutingPersonsStore(stores.pg as unknown as BatchWritingPersonsStore, stores.personhog, mode)

    const mergeRequest = () => ({
        teamId: 1,
        targetDistinctId: 'd1',
        sources: [{ distinctId: 'anon-1', eventUuid: 'uuid-1' }],
        eventUuid: 'uuid-1',
    })

    beforeEach(() => {
        defaultRetryConfig.RETRY_INTERVAL_DEFAULT = 0
    })

    describe('shadow divergence detection', () => {
        const divergences = (): Record<string, string>[] =>
            (personhogStoreShadowDivergenceCounter.labels as jest.Mock).mock.calls.map(([labels]) => labels)
        const counted = (): boolean =>
            (personhogStoreShadowDivergenceCounter.labels as jest.Mock).mock.results.every(
                (call) => (call.value.inc as jest.Mock).mock.calls.length > 0
            )

        it.each([
            ['a different person', { uuid: 'other-uuid' }, 'uuid'],
            ['a different identified flag', { is_identified: true }, 'is_identified'],
            ['different properties', { properties: { plan: 'pro' } }, 'properties'],
        ])('records a read answering %s', async (_case, shadowDiff, field) => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            stores.personhogMock.fetchForUpdate.mockResolvedValue({ ...person(1, '1'), ...shadowDiff })
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            // The error counter says personhog fell over. Nothing said it
            // answered a different person, which is the failure shadow mode
            // exists to find.
            expect(divergences()).toContainEqual({ verb: 'fetchForUpdate', field })
            expect(counted()).toBe(true)
        })

        it('records a read that found nobody where the authoritative one found somebody', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            stores.personhogMock.fetchForUpdate.mockResolvedValue(null)
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            expect(divergences()).toContainEqual({ verb: 'fetchForUpdate', field: 'missing_shadow' })
        })

        it('records nothing when the two agree', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            stores.personhogMock.fetchForUpdate.mockResolvedValue(person(1, '1'))
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            expect(divergences()).toEqual([])
            expect(personhogStoreShadowComparedCounter.labels).toHaveBeenCalledWith({ verb: 'fetchForUpdate' })
        })

        it.each([
            ['empty properties', { properties: {} }, []],
            ['another person', { uuid: 'other-uuid' }, [{ verb: 'fetchForChecking', field: 'uuid' }]],
        ])(
            'compares a checking read on identity only, given a shadow answer with %s',
            async (_case, shadowDiff, expected) => {
                const stores = makeStores()
                stores.pg.fetchForChecking.mockResolvedValue({ ...person(1, '1'), properties: { plan: 'pro' } })
                stores.personhogMock.fetchForChecking.mockResolvedValue({ ...person(1, '1'), ...shadowDiff })
                const store = makeStore(stores, 'shadow')

                await store.fetchForChecking(1, 'd1', 0)

                // personhog answers a checking read from the identity service, without properties.
                expect(divergences()).toEqual(expected)
                expect(personhogStoreShadowComparedCounter.labels).toHaveBeenCalledWith({ verb: 'fetchForChecking' })
            }
        )

        it.each([
            ['a nested object whose keys arrived in another order', { a: 1, b: 2 }, { b: 2, a: 1 }, false],
            ['an array whose order actually differs', [1, 2], [2, 1], true],
        ])('reads %s correctly', async (_case, pgValue, shadowValue, diverges) => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue({ ...person(1, '1'), properties: { nested: pgValue } })
            stores.personhogMock.fetchForUpdate.mockResolvedValue({
                ...person(1, '1'),
                properties: { nested: shadowValue },
            })
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            // Postgres stores jsonb in its own key order while the personhog
            // side arrives in the order it was written, so comparing
            // serialised forms would call every nested object a difference
            // and bury the ones that are real. Array order is the customer's.
            expect(divergences().some((labels) => labels.field === 'properties')).toBe(diverges)
        })

        it('records a merge that picked a different survivor', async () => {
            const stores = makeStores()
            stores.pg.mergePersons.mockResolvedValue({ survivor: person(1, '1'), results: [] })
            stores.personhogMock.mergePersons.mockResolvedValue({
                survivor: { ...person(1, '1'), uuid: 'other-uuid' },
                results: [],
            })
            const store = makeStore(stores, 'shadow')

            await store.mergePersons(mergeRequest() as never, 0)

            // Which person survives decides where every later event in the
            // batch lands, and a row diff cannot see it: both sides end with
            // a person that looks plausible on its own.
            expect(divergences()).toContainEqual({ verb: 'mergePersons', field: 'survivor' })
        })

        it('records a source the two backends settled differently', async () => {
            const stores = makeStores()
            stores.pg.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
            })
            stores.personhogMock.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'skipped_already_identified' }],
            })
            const store = makeStore(stores, 'shadow')

            await store.mergePersons(mergeRequest() as never, 0)

            expect(divergences()).toContainEqual({ verb: 'mergePersons', field: 'outcome' })
        })

        it('a verdict only the shadow produced records an outcome divergence', async () => {
            const stores = makeStores()
            stores.pg.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
            })
            stores.personhogMock.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'merged' },
                    { sourceDistinctId: 'anon-2', outcome: 'merged' },
                ],
            })
            const store = makeStore(stores, 'shadow')

            await store.mergePersons(mergeRequest() as never, 0)

            expect(divergences()).toContainEqual({ verb: 'mergePersons', field: 'outcome' })
        })

        it('a fold only one backend aborted records the disposition, without per-source noise', async () => {
            const stores = makeStores()
            stores.pg.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
            })
            stores.personhogMock.mergePersons.mockResolvedValue({
                survivor: null,
                results: [],
                foldAborted: 'conflict',
            })
            const store = makeStore(stores, 'shadow')

            await store.mergePersons(mergeRequest() as never, 0)

            expect(divergences()).toEqual([{ verb: 'mergePersons', field: 'fold_disposition' }])
        })

        const foldRequest = () => ({
            teamId: 1,
            targetDistinctId: 'd1',
            sources: [
                { distinctId: 'anon-1', eventUuid: 'uuid-1' },
                { distinctId: 'anon-2', eventUuid: 'uuid-2' },
            ],
            triggerSourceDistinctId: 'anon-1',
            eventUuid: 'uuid-1',
            eventOps: {
                set: { plan: 'pro' },
                setOnce: {},
                unset: [],
                denied: false,
                shouldForceUpdate: false,
                eventName: '$identify',
            },
            allowIdentifiedSources: false,
            mergeMode: { type: 'SYNC' as const },
            createdAtMs: 1_000,
        })

        it.each([
            ['aborted', () => Promise.resolve({ survivor: null, results: [], foldAborted: 'conflict' as const }), []],
            [
                'failed with no verdict',
                () => Promise.reject(new PersonMergeCallFailedError('no verdict', new Error('shed'))),
                [{ verb: 'mergePersons', error: 'PersonMergeCallFailedError' }],
            ],
        ])(
            'a fold only the shadow %s re-drives each pair as a sequential shadow merge',
            async (_how, shadowFold, counted) => {
                const stores = makeStores()
                stores.pg.mergePersons.mockResolvedValue({
                    survivor: person(1, '1'),
                    results: [
                        { sourceDistinctId: 'anon-1', outcome: 'merged' },
                        { sourceDistinctId: 'anon-2', outcome: 'merged' },
                    ],
                })
                stores.personhogMock.mergePersons.mockImplementationOnce(shadowFold).mockResolvedValue({
                    survivor: person(1, '1'),
                    results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
                })
                const store = makeStore(stores, 'shadow')

                await store.mergePersons(foldRequest() as never, 7)

                // The fold call, then one plain merge per pair: the pair's own
                // event uuid roots the op id, no trigger marks it fold-shaped,
                // and the ops are empty.
                expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(3)
                const pairCalls = stores.personhogMock.mergePersons.mock.calls.slice(1)
                expect(pairCalls.map((call: any[]) => call[0].sources)).toEqual([
                    [{ distinctId: 'anon-1', eventUuid: 'uuid-1' }],
                    [{ distinctId: 'anon-2', eventUuid: 'uuid-2' }],
                ])
                expect(pairCalls.map((call: any[]) => call[0].eventUuid)).toEqual(['uuid-1', 'uuid-2'])
                for (const call of pairCalls) {
                    expect(call[0].triggerSourceDistinctId).toBeUndefined()
                    expect(call[0].eventOps.set).toEqual({})
                }
                expect(
                    (personhogStoreShadowErrorsCounter.labels as jest.Mock).mock.calls.map(([labels]) => labels)
                ).toEqual(counted)
            }
        )

        it('a fold both backends executed re-drives nothing', async () => {
            const stores = makeStores()
            stores.pg.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
            })
            stores.personhogMock.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
            })
            const store = makeStore(stores, 'shadow')

            await store.mergePersons(foldRequest() as never, 7)

            expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(1)
        })

        it.each([
            ['clears on retry', 1, 4],
            ['fails through every attempt', 3, 5],
        ])('a re-drive pair that %s does not stop the remaining pairs', async (_how, failures, expectedCalls) => {
            const stores = makeStores()
            stores.pg.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'merged' },
                    { sourceDistinctId: 'anon-2', outcome: 'merged' },
                ],
            })
            stores.personhogMock.mergePersons.mockResolvedValueOnce({
                survivor: null,
                results: [],
                foldAborted: 'conflict',
            })
            for (let i = 0; i < failures; i++) {
                stores.personhogMock.mergePersons.mockRejectedValueOnce(new Error('redrive transport failure'))
            }
            stores.personhogMock.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [{ sourceDistinctId: 'anon-2', outcome: 'merged' }],
            })
            const store = makeStore(stores, 'shadow')

            await expect(store.mergePersons(foldRequest() as never, 7)).resolves.toBeDefined()

            expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(expectedCalls)
            expect(stores.personhogMock.mergePersons.mock.lastCall?.[0].sources).toEqual([
                { distinctId: 'anon-2', eventUuid: 'uuid-2' },
            ])
        })

        it.each([
            ['a plain merge starts no further attempt', mergeRequest, [], 1],
            [
                'a fold re-drive starts no further pair',
                foldRequest,
                [{ survivor: null, results: [], foldAborted: 'conflict' as const }],
                2,
            ],
        ])('abandoned at the shadow ceiling, %s', async (_name, request, answeredFirst, expectedCalls) => {
            jest.useFakeTimers()
            try {
                const stores = makeStores()
                stores.pg.mergePersons.mockResolvedValue({
                    survivor: person(1, '1'),
                    results: [
                        { sourceDistinctId: 'anon-1', outcome: 'merged' },
                        { sourceDistinctId: 'anon-2', outcome: 'merged' },
                    ],
                })
                let failHanging: (error: Error) => void = () => {}
                const hanging = new Promise<never>((_resolve, reject) => (failHanging = reject))
                for (const answer of answeredFirst) {
                    stores.personhogMock.mergePersons.mockResolvedValueOnce(answer)
                }
                stores.personhogMock.mergePersons.mockReturnValueOnce(hanging)
                const store = makeStore(stores, 'shadow')

                const pending = store.mergePersons(request() as never, 7)
                await jest.advanceTimersByTimeAsync(60_000)
                await pending
                failHanging(new PersonMergeCallFailedError('no verdict', new Error('deadline')))
                await jest.advanceTimersByTimeAsync(1_000)

                expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(expectedCalls)
            } finally {
                jest.useRealTimers()
            }
        })

        it('a fold both backends aborted records and logs nothing', async () => {
            const info = jest.spyOn(logger, 'info')
            const stores = makeStores()
            stores.pg.mergePersons.mockResolvedValue({ survivor: null, results: [], foldAborted: 'limit' })
            stores.personhogMock.mergePersons.mockResolvedValue({
                survivor: null,
                results: [],
                foldAborted: 'conflict',
            })
            const store = makeStore(stores, 'shadow')

            await store.mergePersons(mergeRequest() as never, 0)

            expect(divergences()).toEqual([])
            expect(info).not.toHaveBeenCalledWith('personhog shadow merge verdicts differ', expect.anything())
        })

        it('tells shadow failures apart by class, not just by verb', async () => {
            class PersonhogFenceTimeoutError extends Error {}
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            stores.personhogMock.fetchForUpdate.mockRejectedValue(new PersonhogFenceTimeoutError('held'))
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({
                verb: 'fetchForUpdate',
                error: 'PersonhogFenceTimeoutError',
            })
        })

        it.each([
            ['unreachable', Code.Unavailable, 'Unavailable'],
            ['timed out', Code.DeadlineExceeded, 'DeadlineExceeded'],
            ['refusing', Code.FailedPrecondition, 'FailedPrecondition'],
        ])('separates an identity service that is %s', async (_case, code, label) => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            stores.personhogMock.fetchForUpdate.mockRejectedValue(new ConnectError('rpc failed', code))
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            // Every gRPC fault is the same ConnectError class, so labelling
            // by class puts unreachable, timed out, and refusing in one
            // number — the distinction a rollout most needs.
            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({
                verb: 'fetchForUpdate',
                error: label,
            })
        })

        it('says which side was empty when only one found a person', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(null)
            stores.personhogMock.fetchForUpdate.mockResolvedValue(person(1, '1'))
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            // personhog not having seen a person yet is expected early in a
            // rollout and fades; personhog holding one Postgres lost never is.
            expect(divergences()).toContainEqual({ verb: 'fetchForUpdate', field: 'missing_authoritative' })
        })

        it.each([
            ['shutdown', async (store: RoutingPersonsStore) => await store.shutdown()],
            ['releaseBatch', (store: RoutingPersonsStore) => store.releaseBatch(0)],
        ])('a shadow %s failure does not reach the caller', async (verb, act) => {
            const stores = makeStores()
            stores.personhogMock.shutdown.mockRejectedValue(new Error('lanes still hold ops'))
            stores.personhogMock.abandonBatch.mockImplementation(() => {
                throw new Error('release blew up')
            })
            const store = makeStore(stores, 'shadow')

            // Shadow's contract is that the non-authoritative backend
            // cannot fail the caller; release and shutdown were the two
            // paths that still could.
            await expect(Promise.resolve(act(store))).resolves.not.toThrow()
            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({
                verb,
                error: 'Error',
            })
        })

        it('reads a shadow answer of undefined as absence, not as a comparator fault', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            stores.personhogMock.fetchForUpdate.mockResolvedValue(undefined as never)
            const store = makeStore(stores, 'shadow')

            await expect(store.fetchForUpdate(1, 'd1', 0)).resolves.toEqual(person(1, '1'))

            // Dereferencing it would blame the backend for the comparator's
            // own crash, during the rollout the comparator exists to inform.
            expect(divergences()).toContainEqual({ verb: 'fetchForUpdate', field: 'missing_shadow' })
            expect(personhogStoreShadowErrorsCounter.labels).not.toHaveBeenCalled()
            expect(personhogStoreShadowCompareFailedCounter.labels).not.toHaveBeenCalled()
        })

        it('counts a comparator fault as its own, never as the backend failing', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            // A person-shaped answer whose properties getter throws: the
            // comparison cannot complete, but the backend answered fine.
            stores.personhogMock.fetchForUpdate.mockResolvedValue({
                ...person(1, '1'),
                get properties(): never {
                    throw new Error('exploding properties')
                },
            } as never)
            const store = makeStore(stores, 'shadow')

            await expect(store.fetchForUpdate(1, 'd1', 0)).resolves.toEqual(person(1, '1'))

            expect(personhogStoreShadowCompareFailedCounter.labels).toHaveBeenCalledWith({ verb: 'fetchForUpdate' })
            expect(personhogStoreShadowErrorsCounter.labels).not.toHaveBeenCalled()
        })
    })

    it('rejects an unknown mode at parse time', () => {
        expect(() => parsePersonsStoreMode('both')).toThrow('PERSONS_STORE_MODE')
        expect(parsePersonsStoreMode('shadow')).toBe('shadow')
    })

    it.each([
        ['shadow', '', 'id:1', 'PERSONHOG_ADDR'],
        ['personhog', 'router:1', '', 'PERSONHOG_IDENTITY_ADDR'],
        ['shadow', '', '', 'PERSONHOG_ADDR and PERSONHOG_IDENTITY_ADDR'],
    ] as const)('%s mode without endpoints fails at boot naming the knob', (mode, routerAddr, identityAddr, named) => {
        expect(() => assertPersonsStoreModeConfig(mode, { routerAddr, identityAddr })).toThrow(named)
    })

    it('pg mode needs no endpoints', () => {
        expect(() => assertPersonsStoreModeConfig('pg', { routerAddr: '', identityAddr: '' })).not.toThrow()
    })

    describe('personhog mode', () => {
        it('routes every verb to personhog, never touching pg', async () => {
            const stores = makeStores()
            const store = makeStore(stores, 'personhog')

            await store.fetchForUpdate(1, 'a', 0)
            await store.fetchForUpdate(2, 'b', 0)
            expect(stores.personhogMock.fetchForUpdate).toHaveBeenCalledTimes(2)
            expect(stores.pg.fetchForUpdate).not.toHaveBeenCalled()
        })

        it('a personhog flush failure propagates, because the store is authoritative', async () => {
            const stores = makeStores()
            stores.personhogMock.flush.mockRejectedValue(new Error('leader down'))
            const store = makeStore(stores, 'personhog')
            await expect(store.flush()).rejects.toThrow('leader down')
        })

        it('mergePersons routes to the personhog store', async () => {
            const stores = makeStores()
            const saga = emptyMergeResult()
            stores.personhogMock.mergePersons.mockResolvedValue(saga)
            const store = makeStore(stores, 'personhog')
            await expect(store.mergePersons({} as never, 0)).resolves.toBe(saga)
            expect(stores.pg.mergePersons).not.toHaveBeenCalled()
        })

        it('flush never runs the pg side, and returns the personhog results', async () => {
            const stores = makeStores()
            const store = makeStore(stores, 'personhog')
            await expect(store.flush()).resolves.toEqual([])
            expect(stores.personhogMock.flush).toHaveBeenCalled()
            expect(stores.pg.flush).not.toHaveBeenCalled()
        })
    })

    describe('shadow mode', () => {
        it('pg is authoritative and the personhog verb runs shadowed', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '7'))
            stores.personhogMock.fetchForUpdate.mockResolvedValue(person(1, '99'))
            const store = makeStore(stores, 'shadow')

            const result = await store.fetchForUpdate(1, 'a', 0)

            expect(result?.id).toBe('7')
            expect(stores.personhogMock.fetchForUpdate).toHaveBeenCalled()
        })

        it('a shadow failure is swallowed and counted, never failing the batch', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '7'))
            stores.personhogMock.fetchForUpdate.mockRejectedValue(new Error('identity down'))
            const store = makeStore(stores, 'shadow')

            const result = await store.fetchForUpdate(1, 'a', 0)

            expect(result?.id).toBe('7')
            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({
                verb: 'fetchForUpdate',
                error: 'Error',
            })
            expect(mockShadowTimerStop).toHaveBeenCalled()
        })

        it('a shadow verb that outruns its ceiling is abandoned, not waited out', async () => {
            // The shadow leg is awaited, so an unbounded one spends the
            // consumer's poll budget and costs the group its membership.
            jest.useFakeTimers()
            try {
                const stores = makeStores()
                stores.pg.fetchForUpdate.mockResolvedValue(person(1, '7'))
                stores.personhogMock.fetchForUpdate.mockReturnValue(new Promise(() => {}))
                const store = makeStore(stores, 'shadow')

                const pending = store.fetchForUpdate(1, 'a', 0)
                let settled = false
                void pending.then(() => (settled = true))
                await Promise.resolve()
                expect(settled).toBe(false)

                jest.advanceTimersByTime(60_000)
                const result = await pending

                expect(result?.id).toBe('7')
                expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({
                    verb: 'fetchForUpdate',
                    error: 'ShadowVerbTimeoutError',
                })
            } finally {
                jest.useRealTimers()
            }
        })

        it('a shadow flush failure is swallowed', async () => {
            const stores = makeStores()
            stores.personhogMock.flush.mockRejectedValue(new Error('leader down'))
            const store = makeStore(stores, 'shadow')
            await expect(store.flush()).resolves.toEqual([])
        })

        it('the shadow leg completes before the routed call returns', async () => {
            // The swallow-and-count tests observe failures synchronously, so
            // a shadow leg degraded to fire-and-forget would pass them as
            // timing flakes rather than failing red. This pins the await:
            // the routed call must not return while the shadow is running.
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '7'))
            let shadowDone = false
            stores.personhogMock.fetchForUpdate.mockImplementation(async () => {
                await new Promise((resolve) => setImmediate(resolve))
                shadowDone = true
                return null
            })
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'a', 0)

            expect(shadowDone).toBe(true)
        })

        it('shadow createPerson hands both backends the same uuid and answers pg', async () => {
            // Creation is the one write where the caller supplies identity;
            // both backends must receive it unchanged or the shadow's rows
            // diverge on the key downstream data is joined by.
            const stores = makeStores()
            const pgResult = { success: true as const, person: person(1, '7'), messages: [], created: true }
            stores.pg.createPerson.mockResolvedValue(pgResult as never)
            stores.personhogMock.createPerson.mockResolvedValue({
                success: true,
                person: person(1, '99'),
                messages: [],
                created: true,
            } as never)
            const store = makeStore(stores, 'shadow')

            const result = await store.createPerson(
                DateTime.fromMillis(3_600_000, { zone: 'utc' }),
                {},
                {},
                {},
                1,
                null,
                false,
                'caller-supplied-uuid',
                { distinctId: 'd1' },
                undefined,
                undefined,
                0
            )

            expect(result).toBe(pgResult)
            expect(stores.pg.createPerson.mock.calls[0][7]).toBe('caller-supplied-uuid')
            expect(stores.personhogMock.createPerson.mock.calls[0][7]).toBe('caller-supplied-uuid')
        })

        it.each([
            ['found', false, 1],
            ['created', true, 0],
        ])(
            'shadow createPerson re-applies the creation properties only when personhog %s the person pg created',
            async (_case, shadowCreated, applied) => {
                const stores = makeStores()
                const shadowPerson = person(1, '99')
                stores.pg.createPerson.mockResolvedValue({
                    success: true,
                    person: person(1, '7'),
                    messages: [],
                    created: true,
                } as never)
                stores.personhogMock.createPerson.mockResolvedValue({
                    success: true,
                    person: shadowPerson,
                    messages: [],
                    created: shadowCreated,
                } as never)
                const store = makeStore(stores, 'shadow')

                await store.createPerson(
                    DateTime.fromMillis(3_600_000, { zone: 'utc' }),
                    { plan: 'pro' },
                    {},
                    {},
                    1,
                    null,
                    false,
                    'caller-supplied-uuid',
                    { distinctId: 'd1' },
                    undefined,
                    undefined,
                    0
                )

                // As a segment of its own, so later ops for the person do not fold onto the creation properties.
                expect(stores.personhogMock.applyEventOpsAsOwnSegment).toHaveBeenCalledTimes(applied)
                if (applied) {
                    expect(stores.personhogMock.applyEventOpsAsOwnSegment).toHaveBeenCalledWith(
                        shadowPerson,
                        expect.objectContaining({ setOnce: { plan: 'pro' }, shouldForceUpdate: true }),
                        'd1',
                        0
                    )
                }
            }
        )

        const createIn = (store: RoutingPersonsStore, isIdentified = false) =>
            store.createPerson(
                DateTime.fromMillis(3_600_000, { zone: 'utc' }),
                { plan: 'pro' },
                {},
                {},
                1,
                null,
                isIdentified,
                'caller-supplied-uuid',
                { distinctId: 'd1' },
                undefined,
                undefined,
                0
            )
        const createdByPg = {
            success: true,
            person: person(1, '7'),
            messages: [],
            created: true,
        } as never

        const retriable = (): Error =>
            Object.assign(new ConnectError('timed out', Code.DeadlineExceeded), { isRetriable: true })
        const createdByPersonhog = (created: boolean) =>
            ({ success: true, person: person(1, '99'), messages: [], created }) as never
        const shadowErrorsRecorded = (): number =>
            (personhogStoreShadowErrorsCounter.labels as jest.Mock).mock.calls.length
        const retriesRecorded = (): number =>
            (personhogStoreShadowCreateRetriesCounter.labels as jest.Mock).mock.calls.length

        it.each([
            ['retriable', retriable()],
            ['cancelled', new ConnectError('canceled', Code.Canceled)],
        ])(
            'a shadow createPerson whose failure is %s retries in place and lands before the event returns',
            async (_case, failure) => {
                jest.useFakeTimers()
                try {
                    const stores = makeStores()
                    stores.pg.createPerson.mockResolvedValue(createdByPg)
                    stores.personhogMock.createPerson
                        .mockRejectedValueOnce(failure)
                        .mockResolvedValueOnce(createdByPersonhog(true))
                    const store = makeStore(stores, 'shadow')
                    const errorsBefore = shadowErrorsRecorded()

                    const creating = createIn(store)
                    await jest.advanceTimersByTimeAsync(1_000)
                    const result = await creating

                    expect(result).toBe(createdByPg)
                    expect(stores.personhogMock.createPerson).toHaveBeenCalledTimes(2)
                    expect(stores.personhogMock.holdEventOps).not.toHaveBeenCalled()
                    expect(shadowErrorsRecorded()).toBe(errorsBefore)
                    expect(personhogStoreShadowCreateRetriesCounter.labels).toHaveBeenCalledWith({ outcome: 'retried' })
                    expect(personhogStoreShadowCreateRetriesCounter.labels).toHaveBeenCalledWith({
                        outcome: 'recovered',
                    })
                } finally {
                    jest.useRealTimers()
                }
            }
        )

        it('a shadow createPerson refused for a deterministic reason fails once, counted, with no retry', async () => {
            const stores = makeStores()
            stores.pg.createPerson.mockResolvedValue(createdByPg)
            stores.personhogMock.createPerson.mockRejectedValue(new ConnectError('rejected', Code.InvalidArgument))
            const store = makeStore(stores, 'shadow')
            const errorsBefore = shadowErrorsRecorded()
            const retriesBefore = retriesRecorded()

            expect(await createIn(store)).toBe(createdByPg)

            expect(stores.personhogMock.createPerson).toHaveBeenCalledTimes(1)
            expect(shadowErrorsRecorded()).toBe(errorsBefore + 1)
            expect(retriesRecorded()).toBe(retriesBefore)
        })

        it.each([
            [false, { setOnce: { plan: 'pro' }, shouldForceUpdate: true }],
            [true, { setOnce: { plan: 'pro' }, shouldForceUpdate: true, isIdentified: true }],
        ])(
            'a retried create that finds the person (identified=%p) applies its creation properties set-once',
            async (isIdentified, expected) => {
                jest.useFakeTimers()
                try {
                    const stores = makeStores()
                    stores.pg.createPerson.mockResolvedValue(createdByPg)
                    const existing = createdByPersonhog(false) as { person: InternalPerson }
                    stores.personhogMock.createPerson
                        .mockRejectedValueOnce(retriable())
                        .mockResolvedValueOnce(existing as never)
                    const store = makeStore(stores, 'shadow')

                    const creating = createIn(store, isIdentified)
                    await jest.advanceTimersByTimeAsync(1_000)
                    await creating

                    // Under the event's own batch: the create is still inside the event when it lands.
                    expect(stores.personhogMock.applyEventOpsAsOwnSegment).toHaveBeenCalledWith(
                        existing.person,
                        expect.objectContaining({ ...expected, eventName: '$create_person' }),
                        'd1',
                        0
                    )
                } finally {
                    jest.useRealTimers()
                }
            }
        )

        it('a create still failing at the deadline is counted once', async () => {
            jest.useFakeTimers()
            try {
                const stores = makeStores()
                stores.pg.createPerson.mockResolvedValue(createdByPg)
                stores.personhogMock.createPerson.mockRejectedValue(retriable())
                const store = makeStore(stores, 'shadow')
                const errorsBefore = shadowErrorsRecorded()

                const creating = createIn(store)
                await jest.advanceTimersByTimeAsync(40_000)
                expect(await creating).toBe(createdByPg)

                const attempts = stores.personhogMock.createPerson.mock.calls.length
                // 1 s doubling to 8 s with 5% jitter fits five or six attempts in 20 s; a try count gives another number.
                expect(attempts).toBeGreaterThanOrEqual(5)
                expect(attempts).toBeLessThanOrEqual(6)
                expect(shadowErrorsRecorded()).toBe(errorsBefore + 1)
                expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenLastCalledWith(
                    expect.objectContaining({ verb: 'createPerson' })
                )
            } finally {
                jest.useRealTimers()
            }
        })

        it('in shadow mode the Postgres flush is given the seal to run ahead of each decision round', async () => {
            const stores = makeStores()
            const store = makeStore(stores, 'shadow')

            await store.flush()

            expect(stores.pg.flush).toHaveBeenCalledWith(expect.any(Function))
            expect(stores.personhogMock.sealDecided).toHaveBeenCalledTimes(1)
        })

        it('a shadow fold lands in the same step as its Postgres fold', () => {
            const stores = makeStores()
            stores.personhogMock.applyEventOpsNow.mockReturnValue(true)
            const store = makeStore(stores, 'shadow')

            const folding = store.applyEventOps(person(1, '7'), ops, 'd1', 0)
            // Before any await: a seal issued now could not fall between the two folds.
            expect(stores.pg.foldEventOps).toHaveBeenCalledTimes(1)
            expect(stores.personhogMock.applyEventOpsNow).toHaveBeenCalledWith(1, 'd1', ops, 0, 'uuid-7')
            return folding
        })

        it('the shadow folds an event on the entry the Postgres fold landed it on, not the person the event read', () => {
            const stores = makeStores()
            stores.pg.foldEventOps.mockReturnValue({ result: [person(1, '7'), []], landedOn: 'uuid-9' })
            stores.personhogMock.applyEventOpsNow.mockReturnValue(true)
            const store = makeStore(stores, 'shadow')

            const folding = store.applyEventOps(person(1, '7'), ops, 'd1', 0)

            expect(stores.personhogMock.applyEventOpsNow).toHaveBeenCalledWith(1, 'd1', ops, 0, 'uuid-9')
            return folding
        })

        it('an event the Postgres fold landed nothing for folds nothing on the shadow side, even behind held ops', async () => {
            const stores = makeStores()
            stores.pg.foldEventOps.mockReturnValue({ result: [person(1, '7'), []], landedOn: undefined })
            stores.personhogMock.hasHeldOps.mockReturnValue(true)
            const store = makeStore(stores, 'shadow')

            const [result] = await store.applyEventOps(person(1, '7'), ops, 'd1', 0)

            expect(result.id).toBe('7')
            expect(stores.personhogMock.applyEventOpsNow).not.toHaveBeenCalled()
            expect(stores.personhogMock.holdEventOps).not.toHaveBeenCalled()
        })

        it("a shadow merge seals its sources' segments once it has run, so the next flush writes them", async () => {
            const stores = makeStores()
            stores.pg.landedUuid.mockImplementation((_teamId: number, distinctId: string) =>
                distinctId === 'anon-1' ? 'uuid-anon' : 'uuid-target'
            )
            stores.pg.mergePersons.mockResolvedValue({ survivor: person(1, '7'), results: [] })
            const order: string[] = []
            stores.personhogMock.mergePersons.mockImplementation(() => {
                order.push('merge')
                return Promise.resolve({ survivor: person(1, '7'), results: [] })
            })
            stores.personhogMock.sealDecided.mockImplementation(() => {
                order.push('seal')
            })
            const store = makeStore(stores, 'shadow')

            await store.mergePersons(mergeRequest() as never, 0)

            expect(stores.personhogMock.sealDecided).toHaveBeenCalledWith(['uuid-anon'])
            expect(order).toEqual(['merge', 'seal'])
        })

        it.each([
            ['not resolved yet', false, 'unresolved'],
            ['behind ops already held for its id', true, 'behind_held'],
        ])('a shadow fold for an id %s holds the ops, counted', async (_case, behindHeld, reason) => {
            const stores = makeStores()
            stores.personhogMock.hasHeldOps.mockReturnValue(behindHeld)
            const store = makeStore(stores, 'shadow')

            await store.applyEventOps(person(1, '7'), ops, 'd1', 0)

            expect(stores.personhogMock.holdEventOps).toHaveBeenCalledWith(1, 'd1', ops, 0, 'uuid-7')
            expect(personhogStoreShadowFoldHeldCounter.labels).toHaveBeenCalledWith({ reason })
            expect(stores.personhogMock.applyEventOpsNow).toHaveBeenCalledTimes(behindHeld ? 0 : 1)
        })

        it('a shadow fold that throws is counted and the event still returns the Postgres result', async () => {
            const stores = makeStores()
            stores.personhogMock.applyEventOpsNow.mockImplementation(() => {
                throw new Error('leader down')
            })
            const store = makeStore(stores, 'shadow')

            const [result] = await store.applyEventOps(person(1, '7'), ops, 'd1', 0)

            expect(result.id).toBe('7')
            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith(
                expect.objectContaining({ verb: 'applyEventOps' })
            )
        })

        it('mergePersons replays the same request against the personhog backend, pg staying authoritative', async () => {
            const stores = makeStores()
            const pgResult = { survivor: person(1, '7'), results: [] }
            stores.pg.mergePersons.mockResolvedValue(pgResult)
            const store = makeStore(stores, 'shadow')
            const request = mergeRequest() as never

            await expect(store.mergePersons(request, 0)).resolves.toBe(pgResult)

            expect(stores.pg.mergePersons).toHaveBeenCalledWith(request, 0)
            expect(stores.personhogMock.mergePersons).toHaveBeenCalledWith(request, 0)
        })

        const noVerdict = (): Error => new PersonMergeCallFailedError('no verdict', new Error('shed'))

        it.each([
            ['a no-verdict failure that clears is retried under the same request', [noVerdict()], 2, null, false],
            [
                'a failure through every attempt is counted and re-driven at a flush',
                [noVerdict(), noVerdict(), noVerdict()],
                3,
                'PersonMergeCallFailedError',
                true,
            ],
            [
                'a deterministic refusal is counted without a retry or a re-drive',
                [new ConnectError('refused', Code.InvalidArgument)],
                1,
                'InvalidArgument',
                false,
            ],
        ])('shadow merge: %s', async (_name, failures, expectedCalls, countedAs, redriven) => {
            jest.useFakeTimers()
            try {
                const stores = makeStores()
                stores.pg.mergePersons.mockResolvedValue(emptyMergeResult())
                stores.personhogMock.mergePersons.mockResolvedValue(emptyMergeResult())
                for (const failure of failures) {
                    stores.personhogMock.mergePersons.mockRejectedValueOnce(failure)
                }
                const store = makeStore(stores, 'shadow')
                const request = mergeRequest() as never

                const merging = store.mergePersons(request, 0)
                await jest.advanceTimersByTimeAsync(1_000)
                await expect(merging).resolves.toEqual(emptyMergeResult())

                expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(expectedCalls)
                expect(stores.personhogMock.mergePersons).toHaveBeenLastCalledWith(request, 0)
                const counted = (personhogStoreShadowErrorsCounter.labels as jest.Mock).mock.calls.map(
                    ([labels]) => labels
                )
                expect(counted).toEqual(countedAs === null ? [] : [{ verb: 'mergePersons', error: countedAs }])

                // Past the re-drive delay, a flush re-drives only a merge that never got a verdict.
                await jest.advanceTimersByTimeAsync(5_000)
                const flushing = store.flush()
                await jest.advanceTimersByTimeAsync(1_000)
                await flushing
                expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(expectedCalls + (redriven ? 1 : 0))
                if (redriven) {
                    expect(personhogStoreShadowMergeRedriveCounter.labels).toHaveBeenCalledWith({ outcome: 'settled' })
                } else {
                    expect(personhogStoreShadowMergeRedriveCounter.labels).not.toHaveBeenCalled()
                }
            } finally {
                jest.useRealTimers()
            }
        })

        it.each([
            ['settles on a retry', 1, 2, 'merged'],
            ['stays unsettled through every attempt', 3, 3, 'skipped_conflict'],
        ])('shadow merge that %s', async (_name, unsettledAttempts, expectedCalls, finalOutcome) => {
            const stores = makeStores()
            stores.pg.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
            })
            for (let i = 0; i < unsettledAttempts; i++) {
                stores.personhogMock.mergePersons.mockResolvedValueOnce({
                    survivor: person(1, '1'),
                    results: [{ sourceDistinctId: 'anon-1', outcome: 'skipped_conflict', settled: false }],
                })
            }
            stores.personhogMock.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
            })
            const store = makeStore(stores, 'shadow')

            await store.mergePersons(mergeRequest() as never, 0)

            expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(expectedCalls)
            // The outcome the comparator saw: settled after a retry, or the last unsettled verdict.
            const divergences = (personhogStoreShadowDivergenceCounter.labels as jest.Mock).mock.calls.map(([l]) => l)
            expect(divergences.some((d) => d.field === 'outcome')).toBe(finalOutcome !== 'merged')
            expect(personhogStoreShadowErrorsCounter.labels).not.toHaveBeenCalled()
        })

        /** Unsettled through the first `unsettledCalls` calls, settled from then on; call `hangingCall` never answers. */
        const unsettledUntil = (stores: ReturnType<typeof makeStores>, unsettledCalls: number, hangingCall = 0) => {
            stores.pg.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
            })
            stores.personhogMock.mergePersons.mockImplementation(() => {
                const call = stores.personhogMock.mergePersons.mock.calls.length
                if (call === hangingCall) {
                    return new Promise<never>(() => {})
                }
                return Promise.resolve(
                    call <= unsettledCalls
                        ? {
                              survivor: person(1, '1'),
                              results: [{ sourceDistinctId: 'anon-1', outcome: 'skipped_conflict', settled: false }],
                          }
                        : {
                              survivor: person(1, '1'),
                              results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
                          }
                )
            })
        }

        /** A merge whose three attempts all come back unsettled, so the store defers it. */
        const deferredMerge = async (store: RoutingPersonsStore, request: unknown) => {
            const merging = store.mergePersons(request as never, 0)
            await jest.advanceTimersByTimeAsync(1_000)
            await merging
        }

        it.each([
            ['settles at the first re-drive', 3, [4], ['settled'], 'settled'],
            ['settles at a later re-drive', 6, [6, 7], ['deferred', 'settled'], 'settled'],
            [
                'stays unsettled and is dropped once its window closes',
                Infinity,
                [6, 9, 12, 15, 18],
                ['deferred', 'deferred', 'deferred', 'deferred', 'dropped'],
                'dropped',
            ],
        ])(
            'a shadow merge unsettled through its retries %s',
            async (_name, unsettledAttempts, expectedCallsPerFlush, outcomes, finalOutcome) => {
                jest.useFakeTimers()
                try {
                    const stores = makeStores()
                    unsettledUntil(stores, unsettledAttempts)
                    const store = makeStore(stores, 'shadow')
                    const request = mergeRequest() as never
                    await deferredMerge(store, request)
                    expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(3)

                    // A flush inside the delay leaves the merge waiting.
                    await store.flush()
                    expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(3)

                    for (const [index, expectedCalls] of expectedCallsPerFlush.entries()) {
                        // Past the delay each time, and the last re-drive lands inside the window with its next
                        // turn outside it, so the drop happens at that re-drive rather than at a later flush.
                        await jest.advanceTimersByTimeAsync(4_500)
                        const flushing = store.flush()
                        await jest.advanceTimersByTimeAsync(1_000)
                        await flushing
                        expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(expectedCalls)
                        expect(stores.personhogMock.mergePersons).toHaveBeenLastCalledWith(request, 0)
                        expect(personhogStoreShadowMergeRedriveCounter.labels).toHaveBeenNthCalledWith(index + 1, {
                            outcome: outcomes[index],
                        })
                    }
                    // Settled or dropped, the merge is gone from the next flush.
                    await jest.advanceTimersByTimeAsync(5_000)
                    await store.flush()
                    expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(
                        expectedCallsPerFlush[expectedCallsPerFlush.length - 1]
                    )
                    expect(personhogStoreShadowMergeRedriveCounter.labels).toHaveBeenLastCalledWith({
                        outcome: finalOutcome,
                    })
                    expect(personhogStoreShadowErrorsCounter.labels).not.toHaveBeenCalled()
                } finally {
                    jest.useRealTimers()
                }
            }
        )

        it('the ceiling ends a re-drive loop and re-queues the merges it had not run', async () => {
            jest.useFakeTimers()
            try {
                const stores = makeStores()
                // Two deferred merges; the first re-drive's call, the seventh, never answers.
                unsettledUntil(stores, 6, 7)
                const store = makeStore(stores, 'shadow')
                await deferredMerge(store, mergeRequest())
                await deferredMerge(store, mergeRequest())
                await jest.advanceTimersByTimeAsync(5_000)

                const flushing = store.flush()
                await jest.advanceTimersByTimeAsync(60_000)
                await flushing
                expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(7)
                expect(personhogStoreShadowMergeRedriveCounter.labels).toHaveBeenLastCalledWith({
                    outcome: 'abandoned',
                })

                // Both windows closed while the leg hung, so the next flush drops both rather than leaving them
                // behind the call that never answered.
                await store.flush()

                expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(7)
                const outcomes = (personhogStoreShadowMergeRedriveCounter.labels as jest.Mock).mock.calls.map(
                    ([labels]) => labels.outcome
                )
                expect(outcomes.filter((outcome) => outcome === 'dropped')).toHaveLength(2)
            } finally {
                jest.useRealTimers()
            }
        })

        it('a flush re-drives a bounded number of deferred merges and the rest wait for the next', async () => {
            jest.useFakeTimers()
            try {
                const stores = makeStores()
                const deferrals = 17
                unsettledUntil(stores, deferrals * 3)
                const store = makeStore(stores, 'shadow')
                for (let i = 0; i < deferrals; i++) {
                    await deferredMerge(store, mergeRequest())
                }
                expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(deferrals * 3)

                await jest.advanceTimersByTimeAsync(5_000)
                await store.flush()
                expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(deferrals * 3 + 16)
                await store.flush()
                expect(stores.personhogMock.mergePersons).toHaveBeenCalledTimes(deferrals * 3 + 17)
            } finally {
                jest.useRealTimers()
            }
        })

        it('the store keeps a bounded number of deferred merges and drops the oldest past it', async () => {
            jest.useFakeTimers()
            try {
                const stores = makeStores()
                unsettledUntil(stores, Infinity)
                const store = makeStore(stores, 'shadow')
                for (let i = 0; i < 1_000; i++) {
                    await deferredMerge(store, mergeRequest())
                }
                expect(personhogStoreShadowMergeRedriveCounter.labels).not.toHaveBeenCalled()

                await deferredMerge(store, mergeRequest())

                expect(personhogStoreShadowMergeRedriveCounter.labels).toHaveBeenCalledTimes(1)
                expect(personhogStoreShadowMergeRedriveCounter.labels).toHaveBeenCalledWith({ outcome: 'dropped' })
            } finally {
                jest.useRealTimers()
            }
        })

        it('a flush runs the lanes before the deferred re-drives', async () => {
            jest.useFakeTimers()
            try {
                const stores = makeStores()
                stores.pg.mergePersons.mockResolvedValue({
                    survivor: person(1, '1'),
                    results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
                })
                stores.personhogMock.mergePersons.mockResolvedValue({
                    survivor: person(1, '1'),
                    results: [{ sourceDistinctId: 'anon-1', outcome: 'skipped_conflict', settled: false }],
                })
                const store = makeStore(stores, 'shadow')
                const merging = store.mergePersons(mergeRequest() as never, 0)
                await jest.advanceTimersByTimeAsync(1_000)
                await merging
                stores.personhogMock.mergePersons.mockClear()

                await jest.advanceTimersByTimeAsync(5_000)
                const flushing = store.flush()
                await jest.advanceTimersByTimeAsync(1_000)
                await flushing

                expect(stores.personhogMock.flush.mock.invocationCallOrder[0]).toBeLessThan(
                    stores.personhogMock.mergePersons.mock.invocationCallOrder[0]
                )
            } finally {
                jest.useRealTimers()
            }
        })

        it('prefetch warms both worlds, starting the shadow one before the authoritative one finishes', async () => {
            const stores = makeStores()
            const store = makeStore(stores, 'shadow')
            let finishPg: () => void = () => {}
            stores.pg.prefetchPersons.mockReturnValueOnce(new Promise<void>((resolve) => (finishPg = resolve)))

            const prefetching = store.prefetchPersons([{ teamId: 1, distinctId: 'd', batchId: 0 }])
            expect(stores.pg.prefetchPersons).toHaveBeenCalled()
            expect(stores.personhogMock.prefetchPersons).toHaveBeenCalled()
            finishPg()
            await prefetching
        })

        it('getFlushStats counts a batch once when both worlds reference it', () => {
            const stores = makeStores()
            stores.pg.getFlushStats.mockReturnValue({ dirtyEntryCount: 2, referencedBatchCount: 1, cacheEntryCount: 3 })
            stores.personhogMock.getFlushStats.mockReturnValue({
                dirtyEntryCount: 1,
                referencedBatchCount: 1,
                cacheEntryCount: 2,
            })
            const store = makeStore(stores, 'shadow')
            expect(store.getFlushStats()).toEqual({ dirtyEntryCount: 3, referencedBatchCount: 1, cacheEntryCount: 5 })
        })
    })

    describe('shadow writes resolve the personhog backend person', () => {
        it('a direct diff update writes the shadow backend id, not the pg id', async () => {
            const stores = makeStores()
            stores.pg.updatePersonWithPropertiesDiffForUpdate.mockResolvedValue([person(1, '7'), [], true])
            stores.personhogMock.fetchForUpdate.mockResolvedValue(person(1, '99'))
            stores.personhogMock.updatePersonWithPropertiesDiffForUpdate.mockResolvedValue([person(1, '99'), [], true])
            const store = makeStore(stores, 'shadow')

            await store.updatePersonWithPropertiesDiffForUpdate(person(1, '7'), { a: '1' }, [], {}, 'd1', 0)

            const shadowArgs = stores.personhogMock.updatePersonWithPropertiesDiffForUpdate.mock.calls[0]
            expect((shadowArgs[0] as InternalPerson).id).toBe('99')
        })

        it('holds the ops for a resolve at flush when the person does not exist in the personhog backend', async () => {
            const stores = makeStores()
            stores.personhogMock.fetchForUpdate.mockResolvedValue(null)
            const store = makeStore(stores, 'shadow')

            const [result] = await store.applyEventOps(person(1, '7'), ops, 'd1', 0)

            expect(result.id).toBe('7')
            expect(stores.personhogMock.applyEventOps).not.toHaveBeenCalled()
            expect(stores.personhogMock.holdEventOps).toHaveBeenCalledWith(1, 'd1', ops, 0, 'uuid-7')
            expect(personhogStoreShadowSkipsCounter.labels).not.toHaveBeenCalled()
        })

        it('holds the ops behind ops already held for the distinct id, without resolving the person', async () => {
            const stores = makeStores()
            stores.personhogMock.hasHeldOps.mockReturnValue(true)
            stores.personhogMock.fetchForUpdate.mockResolvedValue(person(1, '99'))
            const store = makeStore(stores, 'shadow')

            await store.applyEventOps(person(1, '7'), ops, 'd1', 0)

            expect(stores.personhogMock.hasHeldOps).toHaveBeenCalledWith(1, 'd1')
            expect(stores.personhogMock.fetchForUpdate).not.toHaveBeenCalled()
            expect(stores.personhogMock.applyEventOps).not.toHaveBeenCalled()
            expect(stores.personhogMock.holdEventOps).toHaveBeenCalledWith(1, 'd1', ops, 0, 'uuid-7')
        })

        it('skips a direct diff update, counted, when the person does not exist in the personhog backend', async () => {
            const stores = makeStores()
            stores.pg.updatePersonWithPropertiesDiffForUpdate.mockResolvedValue([person(1, '7'), [], true])
            stores.personhogMock.fetchForUpdate.mockResolvedValue(null)
            const store = makeStore(stores, 'shadow')

            await store.updatePersonWithPropertiesDiffForUpdate(person(1, '7'), { a: '1' }, [], {}, 'd1', 0)

            expect(stores.personhogMock.updatePersonWithPropertiesDiffForUpdate).not.toHaveBeenCalled()
            expect(personhogStoreShadowSkipsCounter.labels).toHaveBeenCalledWith({
                verb: 'updatePersonWithPropertiesDiffForUpdate',
            })
        })
    })

    it('shutdown closes the personhog side even when pg shutdown fails', async () => {
        const stores = makeStores()
        stores.pg.shutdown.mockRejectedValue(new Error('pg teardown failed'))
        const store = makeStore(stores, 'shadow')

        await expect(store.shutdown()).rejects.toThrow('pg teardown failed')
        expect(stores.personhogMock.shutdown).toHaveBeenCalled()
    })

    it('a shadow release abandons the personhog batch rather than keeping it', () => {
        // A shadow flush failure already acked the batch on the pg side, so
        // a plain release would retain the unwritten lanes forever; hours
        // of identity outage would grow them without bound inside the
        // authoritative process.
        const stores = makeStores()
        const store = makeStore(stores, 'shadow')
        store.releaseBatch(4)
        expect(stores.pg.releaseBatch).toHaveBeenCalledWith(4)
        expect(stores.personhogMock.abandonBatch).toHaveBeenCalledWith(4)
        expect(stores.personhogMock.releaseBatch).not.toHaveBeenCalled()
    })

    it('a personhog-mode release keeps unwritten lanes for the next flush', () => {
        const stores = makeStores()
        const store = makeStore(stores, 'personhog')
        store.releaseBatch(4)
        expect(stores.personhogMock.releaseBatch).toHaveBeenCalledWith(4)
        expect(stores.personhogMock.abandonBatch).not.toHaveBeenCalled()
    })
})
