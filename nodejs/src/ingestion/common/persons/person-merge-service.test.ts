import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { PersonClaimedByLifecycleOpError } from '~/common/persons/repositories/person-repository'
import { parseJSON } from '~/common/utils/json-parse'
import { defaultRetryConfig } from '~/common/utils/retries'
import { IngestionWarningLimiter } from '~/common/utils/token-bucket'
import { ingestionWarningCounter } from '~/ingestion/common/ingestion-warnings'
import { PluginEvent } from '~/plugin-scaffold'
import { InternalPerson, Team } from '~/types'

import { PersonContext } from './person-context'
import { MergeFoldPlan } from './person-merge-fold'
import {
    PersonMergeService,
    mergeClaimDroppedCounter,
    mergeFoldFallbackCounter,
    mergeResponseMismatchCounter,
    mergeSettledFailureCounter,
    mergeUnsettledCounter,
} from './person-merge-service'
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

const counterTotal = async (counter: { get: () => Promise<{ values: { value: number }[] }> }): Promise<number> =>
    (await counter.get()).values.reduce((sum, entry) => sum + entry.value, 0)

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
        // The warning limiter is module-global; a leftover bucket would let
        // one test's emission suppress another's.
        IngestionWarningLimiter.storage.buckets.clear()
        store = {
            mergePersons: jest.fn().mockResolvedValue(result('merged')),
            fetchForUpdate: jest.fn().mockResolvedValue(null),
        }
        outputs = { queueMessages: jest.fn().mockResolvedValue(undefined) }
    })

    it('passes a pre-epoch event timestamp through unchanged', async () => {
        // Events stamped before 1970 exist. Clamping them here would rewrite
        // the created_at Postgres records for a person a merge creates, so
        // each backend applies its own storable range instead.
        const service = makeService()
        await service.merge('anon-1', 'd1', 1, DateTime.fromMillis(-86_400_000, { zone: 'utc' }))

        expect(store.mergePersons).toHaveBeenCalledWith(expect.objectContaining({ createdAtMs: -86_400_000 }))
    })

    it('sends the store one request carrying the event identity and policy', async () => {
        const service = makeService()
        const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)

        expect(store.mergePersons).toHaveBeenCalledWith(
            expect.objectContaining({
                teamId: 1,
                targetDistinctId: 'd1',
                sources: [{ distinctId: 'anon-1', eventUuid: 'event-uuid' }],
                eventUuid: 'event-uuid',
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

    it('attributes a multi-result answer to its own source', async () => {
        // A single-source call cannot legitimately receive two results.
        // Decoding is keyed by source rather than position, so an anomalous
        // answer reads this source's own verdict and stays inert.
        store.mergePersons.mockResolvedValue({
            survivor,
            results: [
                { sourceDistinctId: 'anon-9', outcome: 'skipped_already_identified' },
                { sourceDistinctId: 'anon-1', outcome: 'merged' },
            ],
        })
        const service = makeService()

        const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)

        expect(mergeResult.success && mergeResult.person).toBe(survivor)
        // Our source merged; the sibling did not. Reading the first result
        // rather than this source's would warn about an identified source we
        // never asked about.
        const warned = outputs.queueMessages.mock.calls
            .flat(3)
            .filter((entry: any) => entry?.value)
            .map((entry: any) => parseJSON(Buffer.from(entry.value).toString()).type)
        expect(warned).not.toContain('cannot_merge_already_identified')
    })

    it('$merge_dangerously legally merges identified sources', async () => {
        const service = makeService('$merge_dangerously')
        await service.merge('anon-1', 'd1', 1, timestamp)
        expect(store.mergePersons.mock.calls[0][0].allowIdentifiedSources).toBe(true)
    })

    it('a merge call failure retries, then acks with the settled-failure warning', async () => {
        store.mergePersons.mockRejectedValue(
            new PersonMergeCallFailedError('personhog merge call failed with no verdict', new Error('transport'))
        )
        const service = makeService()

        const result = await service.handleIdentifyOrAlias()
        expect(result.success).toBe(true)
        expect(store.mergePersons.mock.calls.length).toBeGreaterThan(1)
        // Postgres gives this loss up silently; the warning is the one
        // deliberate step above parity, so the customer can see it.
        const warned = outputs.queueMessages.mock.calls
            .flat(3)
            .filter((entry: any) => entry?.value)
            .map((entry: any) => parseJSON(Buffer.from(entry.value).toString()).type)
        expect(warned).toContain('merge_settled_failure')
    })

    it('a deterministic raw refusal acks once with a warning instead of wedging the batch', async () => {
        // The op_id_reused refusal is deterministic, so rethrowing or
        // retrying would spin on the same refusal until the recorded op
        // ages out. It must ack once and leave a customer-visible trace.
        const before = await counterTotal(ingestionWarningCounter)
        const settledBefore = await counterTotal(mergeSettledFailureCounter)
        store.mergePersons.mockRejectedValue(
            new ConnectError(
                'op_id was already used for a different request',
                Code.FailedPrecondition,
                new Headers({ 'x-semantic-refusal': 'op_id_reused' })
            )
        )
        const service = makeService()

        await expect(service.handleIdentifyOrAlias()).resolves.not.toThrow()
        expect(store.mergePersons).toHaveBeenCalledTimes(1)
        expect(await counterTotal(ingestionWarningCounter)).toBe(before + 1)
        // The settled-loss series is what a rollout watches; a refusal
        // counted only under the generic failure counter is invisible there.
        expect(await counterTotal(mergeSettledFailureCounter)).toBe(settledBefore + 1)
    })

    it.each([
        ['a NUL-bearing source id', 'anon\u0000one'],
        ['an over-length source id', 'x'.repeat(150) + '\u{1F600}'.repeat(300)],
    ])('never merges through %s no backend can store', async (_label, badId) => {
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

    it('an unsettled verdict retries under one request and drops with the race warning', async () => {
        // A retry may change the answer, so it happens in-process under
        // the same op id; exhaustion drops the merge the way Postgres
        // drops a persistent conflict.
        // Snapshots taken per call, so a request mutated or rebuilt between
        // attempts cannot compare equal to itself.
        const seenRequests: unknown[] = []
        store.mergePersons.mockImplementation((request: unknown) => {
            seenRequests.push(structuredClone(request))
            return Promise.resolve({
                survivor: null,
                results: [{ sourceDistinctId: 'anon-1', outcome: 'skipped_conflict' as const, settled: false }],
            })
        })
        mergeUnsettledCounter.reset()
        mergeClaimDroppedCounter.reset()
        const service = makeService()
        const result = await service.merge('anon-1', 'd1', 1, timestamp)
        expect(result.success).toBe(true)
        expect(seenRequests.length).toBeGreaterThan(1)
        // Every attempt re-presented an identical request, which the op id
        // derives from.
        for (const seen of seenRequests) {
            expect(seen).toEqual(seenRequests[0])
        }
        // One drop, not one count per attempt, and it reads on the same
        // drop-rate series the other race drops feed.
        expect(await counterTotal(mergeUnsettledCounter)).toBe(1)
        expect(await counterTotal(mergeClaimDroppedCounter)).toBe(1)
        const warned = outputs.queueMessages.mock.calls
            .flat(3)
            .filter((entry: any) => entry?.value)
            .map((entry: any) => parseJSON(Buffer.from(entry.value).toString()).type)
        expect(warned).toContain('merge_race_condition')
    })

    it('a settled verdict this build cannot name acks as a settled loss', async () => {
        // The settled bit is the durability contract; the outcome name only
        // picks the warning. A newer backend's verdict therefore acks
        // instead of wedging the partition or routing to the DLQ.
        store.mergePersons.mockResolvedValue(result('unknown'))
        mergeSettledFailureCounter.reset()
        const service = makeService()

        const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)

        expect(mergeResult.success).toBe(true)
        // 'unknown' may in fact have merged, so it stays off the loss counter.
        expect((await mergeSettledFailureCounter.get()).values[0]?.value ?? 0).toBe(0)
    })

    it('a settled conflict drops with the race warning, as Postgres drops one', async () => {
        store.mergePersons.mockResolvedValue({
            survivor: null,
            results: [{ sourceDistinctId: 'anon-1', outcome: 'skipped_conflict' as const, settled: true }],
        })
        mergeClaimDroppedCounter.reset()
        const service = makeService()

        const mergeResult = await service.merge('anon-1', 'd1', 1, timestamp)

        expect(mergeResult.success).toBe(true)
        expect(store.mergePersons).toHaveBeenCalledTimes(1)
        const warned = outputs.queueMessages.mock.calls
            .flat(3)
            .filter((entry: any) => entry?.value)
            .map((entry: any) => parseJSON(Buffer.from(entry.value).toString()).type)
        expect(warned).toContain('merge_race_condition')
        expect(warned).not.toContain('merge_settled_failure')
        // The drop counts on the same series the fold path feeds.
        expect(await counterTotal(mergeClaimDroppedCounter)).toBe(1)
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

        it.each([
            ['skipped_illegal', 'cannot_merge_with_illegal_distinct_id'],
            ['skipped_conflict', 'merge_race_condition'],
            ['skipped_race', 'merge_race_condition'],
            ['skipped_already_identified', 'cannot_merge_already_identified'],
        ])('warns on a %s source the fold skipped', async (outcome, warningType) => {
            store.mergePersons.mockResolvedValue({
                survivor,
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'merged' },
                    { sourceDistinctId: 'anon-2', outcome },
                ],
            })
            const service = makeService('$identify', makePlan())

            await service.handleIdentifyOrAlias()

            const warned = outputs.queueMessages.mock.calls
                .flat(3)
                .filter((entry: any) => entry?.value)
                .map((entry: any) => parseJSON(Buffer.from(entry.value).toString()).type)
            expect(warned).toContain(warningType)
        })

        it('a source the fold settled as failed leaves a customer-visible trace', async () => {
            // The op is terminal and the source's own event later acks, so
            // dropping this arm would make the lost merge silent. Asserted
            // on the counter because the warning is debounced per team and
            // type.
            const before = await counterTotal(mergeSettledFailureCounter)
            store.mergePersons.mockResolvedValue({
                survivor,
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'merged' },
                    { sourceDistinctId: 'anon-2', outcome: 'error' },
                ],
            })
            const service = makeService('$identify', makePlan())

            await service.handleIdentifyOrAlias()

            expect(await counterTotal(mergeSettledFailureCounter)).toBe(before + 1)
        })

        it('a source dropped to a lifecycle claim counts on the rollout drop signal', async () => {
            const before = await counterTotal(mergeClaimDroppedCounter)
            store.mergePersons.mockResolvedValue({
                survivor,
                results: [
                    { sourceDistinctId: 'anon-1', outcome: 'skipped_conflict' },
                    { sourceDistinctId: 'anon-2', outcome: 'merged' },
                ],
            })
            const service = makeService('$identify', makePlan())

            await service.handleIdentifyOrAlias()

            // The single-source path counts this drop. Counting only that one
            // makes the rollout's drop rate read low by whatever folds.
            expect(await counterTotal(mergeClaimDroppedCounter)).toBe(before + 1)
        })

        it('awaits a committed bootstrap’s delivery before falling back', async () => {
            const order: string[] = []
            let deliver: () => void = () => {}
            const ack = new Promise<void>((resolve) => {
                deliver = () => {
                    order.push('delivered')
                    resolve()
                }
            })
            store.mergePersons.mockResolvedValueOnce({
                survivor: null,
                results: [],
                foldAborted: 'conflict',
                kafkaAck: ack,
            })
            store.mergePersons.mockImplementation(() => {
                order.push('fallback')
                return Promise.resolve(result('merged'))
            })
            const service = makeService('$identify', makePlan())

            const running = service.handleIdentifyOrAlias()
            await new Promise((resolve) => setTimeout(resolve, 0))

            // The rollback did not unmake what the bootstrap committed and
            // produced. Falling back before that delivery lets the event ack
            // ahead of a person row that never reached ClickHouse.
            expect(order).toEqual([])
            deliver()
            await running
            expect(order).toEqual(['delivered', 'fallback'])
        })

        it('a rejected bootstrap ack still abandons the aborted fold', async () => {
            store.mergePersons
                .mockImplementationOnce(() =>
                    Promise.resolve({
                        survivor: null,
                        results: [],
                        foldAborted: 'conflict',
                        kafkaAck: Promise.reject(new Error('produce failed')),
                    })
                )
                .mockResolvedValue(result('merged'))
            const plan = makePlan()
            const service = makeService('$identify', plan)

            // The rejection reaches the generic catch; the plan must not be
            // left re-attempting folds for every later event.
            await expect(service.handleIdentifyOrAlias()).resolves.toMatchObject({ success: true })
            expect(plan.status).toBe('abandoned')
        })

        it('a verdict this build cannot name abandons the fold rather than acking the run', async () => {
            store.mergePersons
                .mockResolvedValueOnce({
                    survivor,
                    results: [
                        { sourceDistinctId: 'anon-1', outcome: 'unknown' },
                        { sourceDistinctId: 'anon-2', outcome: 'merged' },
                    ],
                })
                .mockResolvedValue(result('merged'))
            const plan = makePlan()
            const service = makeService('$identify', plan)

            await service.handleIdentifyOrAlias()

            // Marking the plan executed would ack every event in the run on
            // a verdict nobody can read. Abandoning sends each event down the
            // single-source path, which fails the batch and redelivers once
            // the fleet has caught up.
            expect(plan.status).toBe('abandoned')
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

        it('a fold response missing a verdict for a source fails the batch', async () => {
            store.mergePersons.mockResolvedValue({ survivor, results: [] })
            mergeResponseMismatchCounter.reset()
            const plan = makePlan()
            const service = makeService('$identify', plan)

            await expect(service.handleIdentifyOrAlias()).rejects.toThrow(PersonMergeResponseMismatchError)
            // The stall this causes must be attributable on the mismatch series.
            expect(await counterTotal(mergeResponseMismatchCounter)).toBe(1)
        })

        it('a fold whose call returned no verdict falls back to sequential merges', async () => {
            // A fence the saga still holds drops the sequential re-merges
            // with race warnings until the sweeper settles it.
            store.mergePersons.mockRejectedValue(new PersonMergeCallFailedError('no verdict', new Error('transport')))
            const plan = makePlan()
            const service = makeService('$identify', plan)

            const result = await service.handleIdentifyOrAlias()
            expect(result.success).toBe(true)
            expect(plan.status).toBe('abandoned')
        })

        it('a mismatched merge response fails the batch instead of acking', async () => {
            // The merge never happened, so acking would lose it permanently:
            // the generic catch below returns success, and redelivery is the
            // only thing that could still complete it.
            store.mergePersons.mockRejectedValue(new PersonMergeResponseMismatchError('no verdict for anon-1'))
            const service = makeService('$identify', makePlan())

            await expect(service.handleIdentifyOrAlias()).rejects.toThrow(PersonMergeResponseMismatchError)
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
            const plan = makePlan()
            const service = makeService('$identify', plan)
            // Stubbed on the service rather than through queueMessages:
            // emitIngestionWarning swallows a produce rejection and answers
            // false, so a rejecting broker never reaches the catch this pins.
            jest.spyOn(service as any, 'emitFoldWarnings').mockRejectedValue(new Error('warning emission failed'))

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
