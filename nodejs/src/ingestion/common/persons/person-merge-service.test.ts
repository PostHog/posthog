import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { PersonClaimedByLifecycleOpError } from '~/common/persons/repositories/person-repository'
import { parseJSON } from '~/common/utils/json-parse'
import { defaultRetryConfig } from '~/common/utils/retries'
import { PluginEvent } from '~/plugin-scaffold'
import { InternalPerson, Team } from '~/types'

import { PersonContext } from './person-context'
import { MergeFoldPlan } from './person-merge-fold'
import { PersonMergeService, mergeFoldFallbackCounter } from './person-merge-service'
import {
    PersonMergeCallFailedError,
    PersonMergeLimitExceededError,
    PersonMergeResponseMismatchError,
    SourcePersonHasDistinctIdsError,
    SourcePersonNotFoundError,
    TargetPersonNotFoundError,
    createDefaultSyncMergeMode,
} from './person-merge-types'
import { MergePersonsOutcome, MergePersonsResult } from './persons-store'
import { PersonsStoreForBatch } from './persons-store-for-batch'

describe('PersonMergeService store-owned merges', () => {
    const timestamp = DateTime.fromMillis(3_600_000, { zone: 'utc' })

    const survivor: InternalPerson = {
        id: '7',
        uuid: 'person-uuid',
        team_id: 1,
        properties: { plan: 'merged' },
        created_at: timestamp,
        version: 5,
        properties_last_updated_at: {},
        properties_last_operation: {},
        is_user_id: null,
        is_identified: true,
        last_seen_at: null,
    }

    let store: {
        mergePersons: jest.Mock
        fetchForUpdate: jest.Mock
    }
    let outputs: { queueMessages: jest.Mock }

    const makeService = (eventName = '$identify', mergeFoldPlan?: MergeFoldPlan) => {
        const event = {
            event: eventName,
            uuid: 'event-uuid',
            distinct_id: 'd1',
            team_id: 1,
            properties: {
                $anon_distinct_id: 'anon-1',
                alias: 'anon-1',
                $set: { plan: 'pro' },
                $set_once: { first: 'x' },
            },
        } as unknown as PluginEvent
        const context = new PersonContext(
            event,
            { id: 1 } as Team,
            'd1',
            timestamp,
            true,
            outputs as never,
            store as unknown as PersonsStoreForBatch,
            0,
            createDefaultSyncMergeMode(),
            false,
            false,
            mergeFoldPlan
        )
        return new PersonMergeService(context)
    }

    const result = (outcome: MergePersonsOutcome): MergePersonsResult => ({
        survivor,
        results: [{ sourceDistinctId: 'anon-1', outcome }],
    })

    beforeEach(() => {
        defaultRetryConfig.RETRY_INTERVAL_DEFAULT = 0
        store = {
            mergePersons: jest.fn().mockResolvedValue(result('merged')),
            fetchForUpdate: jest.fn().mockResolvedValue(null),
        }
        outputs = { queueMessages: jest.fn().mockResolvedValue(undefined) }
    })

    it('sends the store one request carrying the event identity and policy', async () => {
        const service = makeService()
        const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)

        expect(store.mergePersons).toHaveBeenCalledWith(
            expect.objectContaining({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                opId: 'event-uuid',
                allowIdentifiedSources: false,
                createdAtMs: 3_600_000,
                eventOps: expect.objectContaining({
                    set: { plan: 'pro' },
                    setOnce: { first: 'x' },
                    eventName: '$identify',
                }),
            })
        )
        expect(mergeResult.success && mergeResult.person?.version).toBe(5)
        expect(store.fetchForUpdate).not.toHaveBeenCalled()
    })

    it('a settled merge failure acks with a signal rather than stalling the partition', async () => {
        store.mergePersons.mockResolvedValue(result('error'))
        const service = makeService()

        const mergeResult = await service.handleIdentifyOrAlias()

        // The verdict is recorded against the op id and replayed for the
        // retention window, so failing the batch would stall the partition
        // instead of healing. The warning is what keeps the lost merge findable.
        expect(mergeResult.success).toBe(true)
        const warned = outputs.queueMessages.mock.calls
            .flat(3)
            .filter((entry: any) => entry?.value)
            .map((entry: any) => parseJSON(Buffer.from(entry.value).toString()).type)
        expect(warned).toContain('merge_settled_failure')
    })

    it('attributes a replayed fold verdict to its own source', async () => {
        // A fold that failed after the saga recorded its op replays under the
        // same op id, carrying every source of the original fold.
        store.mergePersons.mockResolvedValue({
            survivor,
            results: [
                { sourceDistinctId: 'anon-9', outcome: 'merged' },
                { sourceDistinctId: 'anon-1', outcome: 'merged' },
            ],
        })
        const service = makeService()

        const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)

        expect(mergeResult.success && mergeResult.person).toBe(survivor)
    })

    it('$merge_dangerously legally merges identified sources', async () => {
        const service = makeService('$merge_dangerously')
        await service.merge('anon-1', 'd1', 1, timestamp)
        expect(store.mergePersons.mock.calls[0][0].allowIdentifiedSources).toBe(true)
    })

    it('a merge call failure fails the batch instead of acking through the generic catch', async () => {
        // The store wraps verdictless failures in the typed error; the
        // world-agnostic catch must rethrow it — an ack here loses the
        // merge whenever the saga did not commit. The Postgres path never
        // produces this type, so its handling is untouched.
        store.mergePersons.mockRejectedValue(
            new PersonMergeCallFailedError('personhog merge call failed with no verdict', new Error('transport'))
        )
        const service = makeService()

        await expect(service.handleIdentifyOrAlias()).rejects.toThrow(PersonMergeCallFailedError)
    })

    it.each([
        ['a NUL-bearing source id', 'anon\u0000one'],
        ['an over-length source id', 'x'.repeat(150) + '\u{1F600}'.repeat(300)],
    ])('never merges through %s no world can store', async (_label, badId) => {
        // Postgres text cannot hold NUL and varchar(400) cannot hold the id,
        // so the server refuses the whole request INVALID_ARGUMENT on every
        // delivery. Settling client-side with the illegal warning is the
        // only convergent answer.
        const service = makeService()
        const mergeResult = await service.merge(badId, 'd1', 1, timestamp)

        expect(mergeResult.success).toBe(true)
        expect(store.mergePersons).not.toHaveBeenCalled()
        const warned = outputs.queueMessages.mock.calls
            .flat(3)
            .filter((entry: any) => entry?.value)
            .map((entry: any) => parseJSON(Buffer.from(entry.value).toString()).type)
        expect(warned).toContain('cannot_merge_with_illegal_distinct_id')
    })

    it('a FAILED_PRECONDITION call failure salts the retry op id', async () => {
        // A recorded op refuses a drifted redelivery forever under one op
        // id (payloads legitimately drift — GeoIP refreshes, transformation
        // stamps), so the retry must run as a fresh op, which settles as a
        // no-op when the recorded merge committed.
        const opIds: string[] = []
        store.mergePersons.mockImplementation((request: { opId: string }) => {
            opIds.push(request.opId)
            if (opIds.length === 1) {
                return Promise.reject(
                    new PersonMergeCallFailedError(
                        'personhog merge call failed with no verdict: op_id was already used',
                        new ConnectError('op_id was already used for a different request', Code.FailedPrecondition)
                    )
                )
            }
            return Promise.resolve(result('merged'))
        })
        const service = makeService()

        const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)

        expect(mergeResult.success).toBe(true)
        expect(opIds).toHaveLength(2)
        expect(opIds[1]).not.toBe(opIds[0])
        expect(opIds[1]).toContain(opIds[0])
        // The salt is the payload fingerprint, not an attempt counter: a
        // counter restarts every delivery, so a few payload-drifting
        // redeliveries exhaust its reachable op ids and the merge wedges
        // behind recorded mismatches forever. The fingerprint is stable
        // within a delivery and fresh for a drifted one.
        expect(opIds[1]).toMatch(/#fp[0-9a-f]{8}$/)
    })

    it('a conflict gets the full retry budget before surfacing as the claim error', async () => {
        store.mergePersons.mockResolvedValue(result('skipped_conflict'))
        const service = makeService()
        await expect(service.merge('anon-1', 'd1', 1, timestamp)).rejects.toBeInstanceOf(
            PersonClaimedByLifecycleOpError
        )
        expect(store.mergePersons).toHaveBeenCalledTimes(3)
        // A saga-aborted conflict is recorded terminally and replays under
        // its op id even after the conflicting op cleared, so every retry
        // after a conflict must present a fresh, salted op id to get a real
        // second look. Safe: a conflict verdict proves nothing was
        // destroyed, so a fresh op cannot double-merge.
        const opIds = store.mergePersons.mock.calls.map(([request]: any[]) => request.opId)
        expect(new Set(opIds).size).toBe(3)
        expect(opIds[1]).toContain(opIds[0])
    })

    it('a conflict that clears on a salted retry still maps the verdict to its source', async () => {
        store.mergePersons.mockResolvedValueOnce(result('skipped_conflict')).mockResolvedValueOnce(result('merged'))
        const service = makeService()
        const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)
        expect(mergeResult.success && mergeResult.person?.version).toBe(5)
        expect(store.mergePersons.mock.calls[1][0].opId).not.toBe(store.mergePersons.mock.calls[0][0].opId)
    })

    it('a conflict that clears on retry merges normally', async () => {
        store.mergePersons.mockResolvedValueOnce(result('skipped_conflict')).mockResolvedValueOnce(result('merged'))
        const service = makeService()
        const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)
        expect(mergeResult.success && mergeResult.person?.version).toBe(5)
    })

    it('an over-limit source returns the limit error result for the merge-mode policy', async () => {
        store.mergePersons.mockResolvedValue(result('skipped_move_limit'))
        const service = makeService()
        const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)
        expect(!mergeResult.success && mergeResult.error).toBeInstanceOf(PersonMergeLimitExceededError)
    })

    it('an already-identified source warns and keeps the survivor', async () => {
        store.mergePersons.mockResolvedValue(result('skipped_already_identified'))
        const service = makeService()
        const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)
        expect(mergeResult.success && mergeResult.person?.uuid).toBe('person-uuid')
        expect(outputs.queueMessages).toHaveBeenCalledTimes(1)
    })

    it('a race verdict warns and keeps the target as the survivor', async () => {
        store.mergePersons.mockResolvedValue(result('skipped_race'))
        const service = makeService()
        const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)
        expect(mergeResult.success && mergeResult.person?.uuid).toBe('person-uuid')
        expect(outputs.queueMessages).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['failed_source_not_found' as const, SourcePersonNotFoundError],
        ['failed_target_not_found' as const, TargetPersonNotFoundError],
        ['failed_source_has_distinct_ids' as const, SourcePersonHasDistinctIdsError],
    ])('a %s verdict returns the typed final error the processor routes on', async (outcome, errorClass) => {
        store.mergePersons.mockResolvedValue({
            survivor: null,
            results: [{ sourceDistinctId: 'anon-1', outcome }],
        })
        const service = makeService()
        const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)
        expect(!mergeResult.success && mergeResult.error).toBeInstanceOf(errorClass)
    })

    it('a response carrying no verdict for the requested source fails rather than acks', async () => {
        store.mergePersons.mockResolvedValue({
            survivor,
            results: [{ sourceDistinctId: 'someone-else', outcome: 'merged' }],
        })
        const service = makeService()

        // Nothing is recorded against the op id for a malformed response, so a
        // retry can still succeed; acking would lose the merge permanently.
        await expect(service.merge('anon-1', 'd1', 1, timestamp)).rejects.toBeInstanceOf(
            PersonMergeResponseMismatchError
        )
    })

    describe('folded merges', () => {
        const makePlan = (): MergeFoldPlan => ({
            targetDistinctId: 'd1',
            pairs: [
                { anonDistinctId: 'anon-1', eventUuid: 'event-uuid' },
                { anonDistinctId: 'anon-2', eventUuid: 'event-uuid-2' },
            ],
            status: 'planned',
        })

        it('sends every planned pair as one multi-source request and memoizes the survivor', async () => {
            store.mergePersons.mockResolvedValue({
                survivor,
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'merged' },
                    { sourceDistinctId: 'anon-2', outcome: 'merged' },
                ],
            })
            const plan = makePlan()
            const service = makeService('$identify', plan)

            const mergeResult = await service.handleIdentifyOrAlias()

            expect(store.mergePersons).toHaveBeenCalledTimes(1)
            expect(store.mergePersons.mock.calls[0][0].sources).toEqual([
                { distinctId: 'anon-1', eventUuid: 'event-uuid' },
                { distinctId: 'anon-2', eventUuid: 'event-uuid-2' },
            ])
            expect(plan.status).toBe('executed')
            expect(plan.mergedPerson).toBe(survivor)
            expect(mergeResult.success && mergeResult.person).toBe(survivor)
        })

        it('warns on an over-limit source the fold skipped', async () => {
            store.mergePersons.mockResolvedValue({
                survivor,
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'merged' },
                    { sourceDistinctId: 'anon-2', outcome: 'skipped_move_limit' },
                ],
            })
            const service = makeService('$identify', makePlan())

            await service.handleIdentifyOrAlias()

            // The source's own event later reads the executed plan and acks, so
            // without this the lost merge leaves no customer-visible trace.
            const warned = outputs.queueMessages.mock.calls
                .flat(3)
                .filter((entry: any) => entry?.value)
                .map((entry: any) => parseJSON(Buffer.from(entry.value).toString()).type)
            expect(warned).toContain('merge_move_limit_exceeded')
        })

        it('a later event of an executed plan short-circuits without a store call', async () => {
            const plan = makePlan()
            plan.status = 'executed'
            plan.mergedPerson = survivor
            const service = makeService('$identify', plan)

            const mergeResult = await service.handleIdentifyOrAlias()

            expect(store.mergePersons).not.toHaveBeenCalled()
            expect(mergeResult.success && mergeResult.person).toBe(survivor)
        })

        it('an aborted fold abandons the plan and falls back to the single-source merge', async () => {
            store.mergePersons
                .mockResolvedValueOnce({ survivor: null, results: [], foldAborted: 'conflict' })
                .mockResolvedValueOnce(result('merged'))
            const plan = makePlan()
            const service = makeService('$identify', plan)

            const mergeResult = await service.handleIdentifyOrAlias()

            expect(plan.status).toBe('abandoned')
            expect(store.mergePersons).toHaveBeenCalledTimes(2)
            expect(store.mergePersons.mock.calls[1][0].sources).toEqual([
                { distinctId: 'anon-1', eventUuid: 'event-uuid' },
            ])
            expect(mergeResult.success && mergeResult.person).toBe(survivor)
        })

        it('carries the triggering source for the cold-start bootstrap', async () => {
            store.mergePersons.mockResolvedValue({
                survivor,
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'merged' },
                    { sourceDistinctId: 'anon-2', outcome: 'merged' },
                ],
            })
            const service = makeService('$identify', makePlan())

            await service.handleIdentifyOrAlias()

            expect(store.mergePersons.mock.calls[0][0].triggerSourceDistinctId).toBe('anon-1')
        })

        it('a committed fold still succeeds when warning emission fails', async () => {
            store.mergePersons.mockResolvedValue({
                survivor,
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'merged' },
                    { sourceDistinctId: 'anon-2', outcome: 'skipped_already_identified' },
                ],
            })
            outputs.queueMessages.mockRejectedValue(new Error('broker down'))
            const plan = makePlan()
            const service = makeService('$identify', plan)

            const mergeResult = await service.handleIdentifyOrAlias()

            expect(plan.status).toBe('executed')
            expect(mergeResult.success && mergeResult.person).toBe(survivor)
        })

        it('a thrown claim conflict abandons the fold under the conflict label', async () => {
            defaultRetryConfig.RETRY_INTERVAL_DEFAULT = 0
            const before =
                (await mergeFoldFallbackCounter.get()).values.find((v) => v.labels.reason === 'conflict')?.value ?? 0
            store.mergePersons.mockRejectedValue(new PersonClaimedByLifecycleOpError('held', 1))
            const plan = makePlan()
            const service = makeService('$identify', plan)

            const mergeResult = await service.handleIdentifyOrAlias()

            expect(plan.status).toBe('abandoned')
            const after =
                (await mergeFoldFallbackCounter.get()).values.find((v) => v.labels.reason === 'conflict')?.value ?? 0
            expect(after).toBe(before + 1)
            // The sequential fallback then exhausts its retries on the same
            // claim and drops the merge, which reports success with no person.
            expect(mergeResult.success && mergeResult.person).toBeUndefined()
        })
    })

    describe('non-blocking warning acks', () => {
        it('an unmergeable id returns before the warning is acked and hands the ack back', async () => {
            let ackWarning!: () => void
            outputs.queueMessages.mockReturnValue(new Promise<void>((resolve) => (ackWarning = resolve)))
            const service = makeService()

            const mergeResult = await service.merge('anon-1', 'null', 1, timestamp)

            expect(mergeResult.success && mergeResult.person).toBeUndefined()
            expect(store.mergePersons).not.toHaveBeenCalled()
            if (!mergeResult.success) {
                throw new Error('unreachable')
            }
            let acked = false
            void mergeResult.kafkaAck.then(() => (acked = true))
            await Promise.resolve()
            expect(acked).toBe(false)
            ackWarning()
            await mergeResult.kafkaAck
            expect(acked).toBe(true)
        })

        it('a refused verdict returns before its warning is acked and hands the ack back', async () => {
            let ackWarning!: () => void
            outputs.queueMessages.mockReturnValue(new Promise<void>((resolve) => (ackWarning = resolve)))
            store.mergePersons.mockResolvedValue(result('skipped_already_identified'))
            const service = makeService()

            const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)

            expect(mergeResult.success && mergeResult.person?.uuid).toBe('person-uuid')
            if (!mergeResult.success) {
                throw new Error('unreachable')
            }
            let acked = false
            void mergeResult.kafkaAck.then(() => (acked = true))
            await Promise.resolve()
            expect(acked).toBe(false)
            ackWarning()
            await mergeResult.kafkaAck
            expect(acked).toBe(true)
        })

        it('a failed warning produce does not fail the event', async () => {
            outputs.queueMessages.mockRejectedValue(new Error('broker down'))
            store.mergePersons.mockResolvedValue(result('skipped_already_identified'))
            const service = makeService()

            const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)

            expect(mergeResult.success).toBe(true)
            if (mergeResult.success) {
                await expect(mergeResult.kafkaAck).resolves.toBeUndefined()
            }
        })
    })
})
