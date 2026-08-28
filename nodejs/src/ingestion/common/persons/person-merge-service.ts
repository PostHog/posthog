import { ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { isDistinctIdUnmergeable } from '~/common/persons/person-utils'
import {
    PersonClaimedByLifecycleOpError,
    PersonTombstoneBlockedError,
} from '~/common/persons/repositories/person-repository'
import { timeoutGuard } from '~/common/utils/db/utils'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { promiseRetry } from '~/common/utils/retries'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'

import { PersonContext } from './person-context'
import {
    PersonMergeCallFailedError,
    PersonMergeLimitExceededError,
    PersonMergeResponseMismatchError,
    PersonMergeResult,
    PersonMergeUnknownOutcomeError,
    SourcePersonHasDistinctIdsError,
    SourcePersonNotFoundError,
    TargetPersonNotFoundError,
    mergeError,
    mergeSuccess,
} from './person-merge-types'
import { extractEventOps } from './person-update'
import {
    MergeFoldAbortReason,
    MergePersonsRequest,
    MergePersonsResult,
    MergePersonsSourceResult,
} from './persons-store'

export const mergeFinalFailuresCounter = new Counter({
    name: 'person_merge_final_failure_total',
    help: 'Number of person merge final failures.',
    // The error class is the constructor name rather than the message, so a
    // failure carrying team ids or distinct ids cannot inflate cardinality.
    labelNames: ['backend', 'call', 'error'],
})

export const mergeFoldFallbackCounter = new Counter({
    name: 'person_merge_fold_fallback_total',
    help: 'Number of merge folds abandoned in favor of the sequential path.',
    labelNames: ['reason'],
})

export const mergeResponseMismatchCounter = new Counter({
    name: 'person_merge_response_mismatch_total',
    help: 'Merge responses carrying no verdict for the source that was asked about, which stalls the partition.',
    labelNames: ['call'],
})

export const mergeUnknownOutcomeCounter = new Counter({
    name: 'person_merge_unknown_outcome_total',
    help: 'Merges failed because the backend answered a verdict this build cannot name, which a deploy skew produces',
})

export const mergeSettledFailureCounter = new Counter({
    name: 'person_merge_settled_failure_total',
    help: 'Merges the merge backend settled on a verdict that merged nothing.',
})

export const mergeMoveLimitDroppedCounter = new Counter({
    name: 'person_merge_move_limit_dropped_total',
    help: 'Merges lost to the saga move limit, by the path that hit it.',
    labelNames: ['path'],
})

export const mergeClaimDroppedCounter = new Counter({
    name: 'person_merge_claim_dropped_total',
    help: 'Merges dropped because another lifecycle operation held a person through every retry.',
    labelNames: ['call'],
})

/** Maps a thrown fold failure to the fallback counter's reason label. */
function foldAbandonReason(error: unknown): MergeFoldAbortReason {
    if (error instanceof PersonClaimedByLifecycleOpError || error instanceof PersonTombstoneBlockedError) {
        return 'conflict'
    }
    if ((error as { code?: string })?.code === '40P01') {
        return 'deadlock'
    }
    return 'error'
}

/**
 * Service responsible for handling person merging operations (identify,
 * alias, merge). World-agnostic: it validates the request, hands the
 * whole merge to the store's own machinery via mergePersons, and maps
 * the per-source outcomes onto one result and warning vocabulary.
 */
export class PersonMergeService {
    constructor(private context: PersonContext) {}

    async handleIdentifyOrAlias(): Promise<PersonMergeResult> {
        /**
         * strategy:
         *   - if the two distinct ids passed don't match and aren't illegal, then mark `is_identified` to be true for the `distinct_id` person
         *   - if a person doesn't exist for either distinct id passed we create the person with both ids
         *   - if only one person exists we add the other distinct id
         *   - if the distinct ids belong to different already existing persons we try to merge them:
         *     - the merge is blocked if the other distinct id (`anon_distinct_id` or `alias` event property) person has `is_identified` true.
         *     - we merge into `distinct_id` person:
         *       - both distinct ids used in the future will map to the person id that was associated with `distinct_id` before
         *       - if person property was defined for both we'll use `distinct_id` person's property going forward
         */
        const timeout = timeoutGuard('Still running "handleIdentifyOrAlias". Timeout warning after 30 sec!')
        try {
            if (
                ['$create_alias', '$merge_dangerously'].includes(this.context.event.event) &&
                this.context.eventProperties['alias']
            ) {
                return await this.merge(
                    String(this.context.eventProperties['alias']),
                    this.context.distinctId,
                    this.context.team.id,
                    this.context.timestamp
                )
            } else if (
                this.context.event.event === '$identify' &&
                '$anon_distinct_id' in this.context.eventProperties
            ) {
                const anonDistinctId = String(this.context.eventProperties['$anon_distinct_id'])
                // Only await the fold path when a plan exists: an extra microtask
                // here measurably shifts event interleaving for plain merges.
                const foldResult = this.context.mergeFoldPlan ? await this.tryFoldedMerge(anonDistinctId) : null
                if (foldResult !== null) {
                    return foldResult
                }
                return await this.merge(
                    anonDistinctId,
                    this.context.distinctId,
                    this.context.team.id,
                    this.context.timestamp
                )
            }
        } catch (e) {
            if (e instanceof PersonClaimedByLifecycleOpError) {
                // Expected contention, not a failure: another lifecycle operation held one of
                // the persons through every retry. Drop the merge with a warning; the event's
                // property updates still apply to whatever the distinct ids resolve to next.
                // The counter is the rollout's drop-rate signal; the warning is debounced by
                // the standard limiter so a long-held claim cannot flood the warnings topic.
                mergeClaimDroppedCounter.labels({ call: this.context.event.event }).inc()
                const warningAck = emitIngestionWarning(this.context.outputs, this.context.team.id, {
                    type: 'merge_race_condition',
                    details: {
                        distinctId: this.context.distinctId,
                        eventUuid: this.context.event.uuid,
                        sourcePersonDistinctId: String(
                            this.context.eventProperties['$anon_distinct_id'] ?? this.context.eventProperties['alias']
                        ),
                        targetPersonDistinctId: this.context.distinctId,
                    },
                    pipelineStep: 'person-merge',
                }).then(() => undefined)
                logger.warn('🤔', 'merge dropped: person claimed by a concurrent lifecycle operation', {
                    team_id: this.context.team.id,
                    distinctId: this.context.distinctId,
                })
                return mergeSuccess(undefined, warningAck, true)
            }
            if (e instanceof PersonMergeResponseMismatchError) {
                // Not a verdict: nothing is recorded against the op id, so a
                // retry can still succeed and the batch must fail rather than
                // ack a merge that never happened.
                throw e
            }
            if (e instanceof PersonMergeCallFailedError) {
                // The personhog store could not get a verdict at all, so the
                // remote outcome is unknowable. Acking would lose the merge
                // whenever the saga did not commit; failing the batch lets
                // redelivery replay it idempotently — the same loud-and-
                // redeliver shape a failed Postgres merge transaction has.
                throw e
            }
            mergeFinalFailuresCounter
                .labels({
                    backend: this.context.personStore.backend,
                    call: this.context.event.event,
                    error: e instanceof Error ? e.constructor.name : 'unknown',
                })
                .inc()
            if (e instanceof ConnectError) {
                // A raw refusal acked here is a settled merge loss
                // (InvalidArgument, or a deterministic semantic refusal such
                // as a reused op id) — a designed verdict, not a
                // malfunction, so it counts on the settled-loss series and
                // logs as a warning instead of landing in error tracking at
                // whatever rate customers duplicate event uuids. Every
                // other settled loss leaves a customer-visible trace, so
                // this one does too.
                mergeSettledFailureCounter.inc()
                logger.warn('🤔', 'merge refused deterministically; settled as lost', {
                    team_id: this.context.team.id,
                    distinctId: this.context.distinctId,
                    event_name: this.context.event.event,
                    error: String(e),
                })
                const warningAck = emitIngestionWarning(this.context.outputs, this.context.team.id, {
                    type: 'merge_settled_failure',
                    details: {
                        distinctId: this.context.distinctId,
                        eventUuid: this.context.event.uuid,
                        sourcePersonDistinctId: String(
                            this.context.eventProperties['$anon_distinct_id'] ?? this.context.eventProperties['alias']
                        ),
                        targetPersonDistinctId: this.context.distinctId,
                        outcome: 'refused',
                    },
                    pipelineStep: 'person-merge',
                }).then(() => undefined)
                return mergeSuccess(undefined, warningAck, true)
            } else {
                captureException(e, {
                    tags: { team_id: this.context.team.id, pipeline_step: 'processPersonsStep' },
                    extra: {
                        location: 'handleIdentifyOrAlias',
                        distinctId: this.context.distinctId,
                        anonId: String(this.context.eventProperties['$anon_distinct_id']),
                        alias: String(this.context.eventProperties['alias']),
                    },
                })
                logger.error('handleIdentifyOrAlias failed', {
                    error: e,
                    team_id: this.context.team.id,
                    distinctId: this.context.distinctId,
                    event_name: this.context.event.event,
                    anon_distinct_id: String(this.context.eventProperties['$anon_distinct_id']),
                    alias: String(this.context.eventProperties['alias']),
                })
            }
        } finally {
            clearTimeout(timeout)
        }
        // For non-merge events or when no merge conditions are met, return success with no person
        return mergeSuccess(undefined, Promise.resolve(), true)
    }

    public async merge(
        otherPersonDistinctId: string,
        mergeIntoDistinctId: string,
        teamId: number,
        timestamp: DateTime
    ): Promise<PersonMergeResult> {
        // No reason to alias person against itself. Done by posthog-node when updating user properties
        if (mergeIntoDistinctId === otherPersonDistinctId) {
            // Create a success result with undefined person to indicate no merge was needed
            return mergeSuccess(undefined, Promise.resolve(), true)
        }
        if (isDistinctIdUnmergeable(mergeIntoDistinctId)) {
            const warningAck = this.emitIllegalDistinctIdWarning(
                mergeIntoDistinctId,
                otherPersonDistinctId,
                this.context.event.uuid
            )
            return mergeSuccess(undefined, warningAck, true)
        }
        if (isDistinctIdUnmergeable(otherPersonDistinctId)) {
            const warningAck = this.emitIllegalDistinctIdWarning(
                otherPersonDistinctId,
                mergeIntoDistinctId,
                this.context.event.uuid
            )
            return mergeSuccess(undefined, warningAck, true)
        }

        this.context.updateIsIdentified = true
        const request = this.buildRequest(
            mergeIntoDistinctId,
            [{ distinctId: otherPersonDistinctId, eventUuid: this.context.event.uuid }],
            timestamp
        )
        // The store owns the whole merge, its own record-escape retries
        // included: retryable conflicts surface here as throws — the
        // Postgres merge throws them directly, the personhog store throws
        // only after its internal salted re-attempts exhaust — and each
        // re-entry runs against fresh state.
        // A raw ConnectError here is a deterministic refusal the store
        // deliberately unwrapped (InvalidArgument, or a semantic refusal
        // like op_id_reused); retrying it re-runs the same comparison.
        const result = await promiseRetry(
            () => this.context.personStore.mergePersons(request),
            'merge_distinct_ids',
            undefined,
            undefined,
            undefined,
            [ConnectError]
        )
        return this.mapSingleSourceResult(result, otherPersonDistinctId, mergeIntoDistinctId)
    }

    /**
     * One request for either backend, single-source or folded. The event
     * uuid doubles as the op id: retries re-enter with the same id and
     * must not merge twice.
     */
    private buildRequest(
        targetDistinctId: string,
        sources: { distinctId: string; eventUuid: string }[],
        timestamp: DateTime,
        triggerSourceDistinctId?: string
    ): MergePersonsRequest {
        return {
            teamId: this.context.team.id,
            targetDistinctId,
            sources,
            triggerSourceDistinctId,
            eventOps: extractEventOps(this.context.event, this.context.updateAllProperties),
            eventUuid: this.context.event.uuid,
            allowIdentifiedSources: this.context.event.event === '$merge_dangerously',
            mergeMode: this.context.mergeMode,
            // Passed as the event stated it, pre-epoch values included: what a
            // backend can store is the backend's constraint, and clamping here
            // would rewrite the created_at Postgres records for a person born
            // from a merge.
            createdAtMs: timestamp.toMillis(),
        }
    }

    /**
     * Folded-merge entry for $identify events that are part of a MergeFoldPlan.
     * Returns null when the event should fall through to the sequential merge
     * path (no plan, pair not planned, plan abandoned, or fold not applicable).
     */
    private async tryFoldedMerge(anonDistinctId: string): Promise<PersonMergeResult | null> {
        const plan = this.context.mergeFoldPlan
        if (
            !plan ||
            plan.targetDistinctId !== this.context.distinctId ||
            !plan.pairs.some((pair) => pair.anonDistinctId === anonDistinctId)
        ) {
            return null
        }

        if (plan.status === 'abandoned') {
            return null
        }

        if (plan.status === 'executed') {
            this.context.updateIsIdentified = true
            return mergeSuccess(plan.mergedPerson, Promise.resolve(), true)
        }

        if (isDistinctIdUnmergeable(plan.targetDistinctId)) {
            // The sequential path emits the per-event warning.
            plan.status = 'abandoned'
            mergeFoldFallbackCounter.labels({ reason: 'illegal_target' }).inc()
            return null
        }

        this.context.updateIsIdentified = true
        const request = this.buildRequest(
            plan.targetDistinctId,
            plan.pairs.map((pair) => ({ distinctId: pair.anonDistinctId, eventUuid: pair.eventUuid })),
            this.context.timestamp,
            anonDistinctId
        )

        let result: MergePersonsResult
        try {
            result = await this.context.personStore.mergePersons(request)
        } catch (error) {
            if (error instanceof PersonMergeResponseMismatchError) {
                // A malformed response is not a fold-shaped failure the
                // sequential path can retry around, so it has to reach the
                // batch instead of being absorbed by the fallback.
                throw error
            }
            if (error instanceof PersonMergeCallFailedError) {
                // No verdict arrived, so the saga may have sealed sources and
                // still be running. The Postgres fold can fall back safely
                // because its abort is a rolled-back transaction that leaves
                // nothing behind; a live saga leaves fences the sequential
                // merges would meet under different op ids and drop. Failing
                // the batch lets redelivery replay the same fold idempotently.
                throw error
            }
            // Any other failure falls back to the sequential path: the current
            // event re-runs its own merge (a no-op if the fold partially
            // landed), and later events process individually with full retries.
            this.abandonFold(plan, foldAbandonReason(error))
            logger.warn('🤔', 'folded merge failed, falling back to sequential merges', {
                team_id: this.context.team.id,
                distinct_id: plan.targetDistinctId,
                pairs: plan.pairs.length,
                error,
            })
            return null
        }
        if (result.foldAborted) {
            // The store already logged its abort with the underlying error.
            // An abort can still carry an ack: a bootstrap that committed
            // before the fold produced its person and distinct-id messages,
            // and the rollback did not unmake them. Awaiting before the
            // fallback keeps the event from acking ahead of its own writes,
            // and a delivery failure fails the batch rather than hiding.
            if (result.kafkaAck) {
                await result.kafkaAck
            }
            this.abandonFold(plan, result.foldAborted)
            return null
        }
        if (!result.survivor) {
            const reason = result.results[0]?.outcome === 'skipped_move_limit' ? 'limit' : 'error'
            this.abandonFold(plan, reason)
            logger.warn('🤔', 'folded merge settled without a survivor, falling back to sequential merges', {
                team_id: this.context.team.id,
                distinct_id: plan.targetDistinctId,
                pairs: plan.pairs.length,
                reason,
            })
            return null
        }

        // A verdict this build cannot name means a backend a release ahead
        // answered something new, and whether that source merged is unknown.
        // Marking the plan executed would ack every event in the run on that
        // unknown, so the fold gives up and each event decides for itself —
        // where the single-source path fails the batch and redelivers.
        const unnamed = result.results.find((source) => source.outcome === 'unknown')
        if (unnamed !== undefined) {
            mergeUnknownOutcomeCounter.inc()
            this.abandonFold(plan, 'error')
            logger.warn('🤔', 'fold settled a source on a verdict this build cannot name', {
                team_id: this.context.team.id,
                source_distinct_id: unnamed.sourceDistinctId,
                target_distinct_id: request.targetDistinctId,
                pairs: plan.pairs.length,
            })
            return null
        }

        plan.status = 'executed'
        plan.mergedPerson = result.survivor
        // Warning acks ride the result's kafkaAck to the batch-end await
        // rather than blocking here. Warnings are diagnostics; a committed
        // fold must still return its result and ack when they fail.
        const warningsAck = this.emitFoldWarnings(result.results, request).catch((error) => {
            logger.warn('🤔', 'fold warning emission failed', { team_id: this.context.team.id, error })
        })
        return mergeSuccess(
            result.survivor,
            Promise.all([result.kafkaAck ?? Promise.resolve(), warningsAck]).then(() => undefined),
            true
        )
    }

    private abandonFold(plan: NonNullable<PersonContext['mergeFoldPlan']>, reason: MergeFoldAbortReason): void {
        plan.status = 'abandoned'
        mergeFoldFallbackCounter.labels({ reason }).inc()
    }

    /**
     * Maps a single-source merge's outcome onto the caller's result and
     * warning vocabulary, so callers see one merge behavior in both
     * worlds.
     */
    private mapSingleSourceResult(
        result: MergePersonsResult,
        otherPersonDistinctId: string,
        mergeIntoDistinctId: string
    ): PersonMergeResult {
        // The verdict is looked up by source rather than taken positionally,
        // so a multi-source response can never be read as this source's
        // answer.
        const sourceResult = result.results.find((source) => source.sourceDistinctId === otherPersonDistinctId)
        if (sourceResult === undefined) {
            // No verdict for the source we asked about: a malformed response,
            // not an answer the backend settled on. It cannot take the
            // settled-failure path, which acks on the promise that the merge
            // did not happen, because a response missing its verdict says
            // nothing about what happened.
            //
            // Redelivery will not clear it either. The saga records the op
            // and replays the recorded outcome for the same op id, so a
            // response that is wrong once is wrong every time and the
            // partition stops advancing. That is the loud failure this
            // deserves — a caller inventing a verdict here would be worse —
            // but it needs to be attributable, so the counter names the team
            // and the log carries the ids to reproduce it with.
            mergeResponseMismatchCounter.labels({ call: this.context.event.event }).inc()
            logger.error('merge response carried no verdict for its requested source; failing the batch', {
                team_id: this.context.team.id,
                event_uuid: this.context.event.uuid,
                source_distinct_id: otherPersonDistinctId,
                target_distinct_id: mergeIntoDistinctId,
                verdicts: result.results.map((source) => source.sourceDistinctId),
            })
            throw new PersonMergeResponseMismatchError(
                `merge response for team ${this.context.team.id} carried no verdict for its requested source`
            )
        }
        const outcome = sourceResult.outcome
        const survivor = result.survivor ?? undefined
        const kafkaAck = result.kafkaAck ?? Promise.resolve()
        switch (outcome) {
            case 'merged':
            case 'attached':
            case 'noop_same_person':
                return mergeSuccess(survivor, kafkaAck, result.survivorNeedsUpdate ?? true)
            case 'skipped_already_identified': {
                // Warning acks ride the result's kafkaAck to the batch-end
                // await rather than blocking the merge here.
                const warningAck = emitIngestionWarning(this.context.outputs, this.context.team.id, {
                    type: 'cannot_merge_already_identified',
                    details: {
                        sourcePersonDistinctId: otherPersonDistinctId,
                        targetPersonDistinctId: mergeIntoDistinctId,
                        distinctId: mergeIntoDistinctId,
                        eventUuid: this.context.event.uuid,
                        personId: survivor?.uuid,
                        otherPersonId: sourceResult?.sourcePersonUuid,
                    },
                    pipelineStep: 'person-merge',
                    alwaysSend: true,
                })
                logger.warn(
                    '🤔',
                    'refused to merge an already identified user via an $identify or $create_alias call',
                    { team_id: this.context.team.id }
                )
                return mergeSuccess(
                    survivor,
                    Promise.all([kafkaAck, warningAck]).then(() => undefined),
                    true
                )
            }
            case 'skipped_illegal': {
                // Both ids are pre-checked in merge(); the saga's own list
                // can be wider, so honor its verdict with the same warning.
                const warningAck = this.emitIllegalDistinctIdWarning(
                    otherPersonDistinctId,
                    mergeIntoDistinctId,
                    this.context.event.uuid
                )
                return mergeSuccess(
                    survivor,
                    Promise.all([kafkaAck, warningAck]).then(() => undefined),
                    true
                )
            }
            case 'skipped_race': {
                // A concurrent merge kept winning the persons through every
                // retry; the merge drops and the target stays the survivor.
                const warningAck = emitIngestionWarning(this.context.outputs, this.context.team.id, {
                    type: 'merge_race_condition',
                    details: {
                        sourcePersonDistinctId: otherPersonDistinctId,
                        targetPersonDistinctId: mergeIntoDistinctId,
                        distinctId: mergeIntoDistinctId,
                        eventUuid: this.context.event.uuid,
                        personId: survivor?.uuid,
                        otherPersonId: sourceResult?.sourcePersonUuid,
                    },
                    pipelineStep: 'person-merge',
                    alwaysSend: true,
                })
                logger.warn('🤔', 'merge race condition detected, too many concurrent merges', {
                    team_id: this.context.team.id,
                })
                return mergeSuccess(
                    survivor,
                    Promise.all([kafkaAck, warningAck]).then(() => undefined),
                    true
                )
            }
            case 'skipped_conflict':
                // Normally converted into a throw inside the retry loop;
                // this backstop keeps the claim-dropped semantics for any
                // path that maps the outcome directly.
                throw new PersonClaimedByLifecycleOpError(
                    'merge saga: a live lifecycle operation holds a person in this merge',
                    this.context.team.id
                )
            case 'skipped_move_limit':
                // The over-limit path: the caller's merge-mode policy
                // (redirect, DLQ) decides what happens to the event.
                return mergeError(new PersonMergeLimitExceededError('person_merge_move_limit_hit'))
            case 'failed_source_not_found':
                return mergeError(new SourcePersonNotFoundError('Source person no longer exists'))
            case 'failed_target_not_found':
                return mergeError(new TargetPersonNotFoundError('Target person no longer exists'))
            case 'failed_source_has_distinct_ids':
                return mergeError(
                    new SourcePersonHasDistinctIdsError(
                        'Cannot delete source person due to concurrent distinct ID additions'
                    )
                )
            case 'unknown':
                // A backend a release ahead answered something this build has
                // no name for. Unlike 'error' that is not a verdict, so the
                // merge may have happened and acking would record a loss that
                // might not exist. Redelivery cannot resolve it either, since
                // every retry reaches the same build until the roll finishes,
                // and a thrown error here restarts the pod. The event goes to
                // the DLQ instead: replayable, and costing nothing meanwhile.
                mergeUnknownOutcomeCounter.inc()
                return mergeError(
                    new PersonMergeUnknownOutcomeError(
                        `merge backend answered an outcome this build cannot name for source ${otherPersonDistinctId}`,
                        outcome
                    )
                )
            case 'skipped_refused':
            case 'error':
            default: {
                // A verdict, not a transient fault: the merge backend records it
                // against the op id and replays it for the retention window, so
                // neither this event's retry nor its redelivery can reach a
                // different answer — failing the batch would stall the partition
                // instead of healing. The merge is lost; the event's property
                // updates still apply, and the customer's next $identify carries
                // a fresh op id that can succeed. Acked, but never silently.
                mergeSettledFailureCounter.inc()
                const warningAck = emitIngestionWarning(this.context.outputs, this.context.team.id, {
                    type: 'merge_settled_failure',
                    details: {
                        sourcePersonDistinctId: otherPersonDistinctId,
                        targetPersonDistinctId: mergeIntoDistinctId,
                        distinctId: mergeIntoDistinctId,
                        eventUuid: this.context.event.uuid,
                        // Both travel because each backend names the person
                        // differently. The saga, which produces this verdict,
                        // sets a row id only for a merged source, so it sends
                        // neither. Postgres has an unreachable arm that would
                        // carry the uuid.
                        otherPersonId: sourceResult.sourcePersonUuid,
                        sourcePersonId: sourceResult.sourcePersonId,
                        outcome,
                    },
                    pipelineStep: 'person-merge',
                })
                logger.warn('🤔', 'merge settled without merging; the pair stays unmerged', {
                    team_id: this.context.team.id,
                    outcome,
                    event_uuid: this.context.event.uuid,
                })
                return mergeSuccess(
                    undefined,
                    Promise.all([kafkaAck, warningAck]).then(() => undefined),
                    true
                )
            }
        }
    }

    /**
     * Per-source warnings for an executed fold, from the same vocabulary
     * the single-source mapper uses. Merge-shaped outcomes warn nothing;
     * conflicts surface as the race-condition warning rather than a
     * throw, because one held source must not fail the whole fold.
     */
    private async emitFoldWarnings(results: MergePersonsSourceResult[], request: MergePersonsRequest): Promise<void> {
        const eventUuidBySource = new Map(request.sources.map((source) => [source.distinctId, source.eventUuid]))
        // Produces are collected and awaited together so a plan full of
        // refused pairs does not serialize warning round-trips.
        const warningAcks: Promise<unknown>[] = []
        for (const sourceResult of results) {
            const eventUuid = eventUuidBySource.get(sourceResult.sourceDistinctId) ?? this.context.event.uuid
            switch (sourceResult.outcome) {
                case 'skipped_already_identified':
                    warningAcks.push(
                        emitIngestionWarning(this.context.outputs, this.context.team.id, {
                            type: 'cannot_merge_already_identified',
                            details: {
                                sourcePersonDistinctId: sourceResult.sourceDistinctId,
                                targetPersonDistinctId: request.targetDistinctId,
                                distinctId: request.targetDistinctId,
                                eventUuid,
                                personId: this.context.mergeFoldPlan?.mergedPerson?.uuid,
                                otherPersonId: sourceResult.sourcePersonUuid,
                            },
                            pipelineStep: 'person-merge',
                            alwaysSend: true,
                        })
                    )
                    break
                case 'skipped_illegal':
                    warningAcks.push(
                        this.emitIllegalDistinctIdWarning(
                            sourceResult.sourceDistinctId,
                            request.targetDistinctId,
                            eventUuid
                        )
                    )
                    break
                case 'skipped_conflict':
                case 'skipped_race':
                    // The same drop the single-source path counts, reached
                    // through a fold instead. Counting only one of them makes
                    // the rollout's drop rate read low by however much of the
                    // traffic folds.
                    mergeClaimDroppedCounter.labels({ call: this.context.event.event }).inc()
                    warningAcks.push(
                        emitIngestionWarning(this.context.outputs, this.context.team.id, {
                            type: 'merge_race_condition',
                            details: {
                                sourcePersonDistinctId: sourceResult.sourceDistinctId,
                                targetPersonDistinctId: request.targetDistinctId,
                                distinctId: request.targetDistinctId,
                                eventUuid,
                                otherPersonId: sourceResult.sourcePersonUuid,
                            },
                            pipelineStep: 'person-merge',
                            alwaysSend: true,
                        })
                    )
                    break
                case 'skipped_move_limit':
                    // Only the saga can answer this inside an executed fold;
                    // the Postgres merge aborts the whole fold instead so each
                    // event gets its own over-limit policy decision. Folding
                    // costs that decision: the source's own event later reads
                    // the executed plan and acks, so in ASYNC mode it loses the
                    // redirect to the async topic it would otherwise get, not
                    // only the merge. Accepted while personhog mode is a testing
                    // path, and surfaced as a customer-visible warning so a lost
                    // merge is identifiable rather than silent. The permanent
                    // fix is saga-side chunked moves.
                    mergeMoveLimitDroppedCounter.labels({ path: 'fold' }).inc()
                    warningAcks.push(
                        emitIngestionWarning(this.context.outputs, this.context.team.id, {
                            type: 'merge_move_limit_exceeded',
                            details: {
                                sourcePersonDistinctId: sourceResult.sourceDistinctId,
                                targetPersonDistinctId: request.targetDistinctId,
                                distinctId: request.targetDistinctId,
                                eventUuid,
                                otherPersonId: sourceResult.sourcePersonUuid,
                                eventDropped: false,
                            },
                            pipelineStep: 'person-merge',
                        })
                    )
                    logger.warn('🤔', 'fold skipped an over-limit source; its merge is dropped', {
                        team_id: this.context.team.id,
                        source_distinct_id: sourceResult.sourceDistinctId,
                        target_distinct_id: request.targetDistinctId,
                        event_uuid: eventUuid,
                    })
                    break
                case 'error':
                    // The merge for this source did not happen and the op is
                    // terminal, so redelivery cannot reach a different
                    // answer. The single-source path treats this as a
                    // settled failure; a fold has to say so too, or the
                    // loss is invisible.
                    mergeSettledFailureCounter.inc()
                    warningAcks.push(
                        emitIngestionWarning(this.context.outputs, this.context.team.id, {
                            type: 'merge_settled_failure',
                            details: {
                                distinctId: this.context.distinctId,
                                eventUuid,
                                sourcePersonDistinctId: sourceResult.sourceDistinctId,
                                targetPersonDistinctId: request.targetDistinctId,
                            },
                            pipelineStep: 'person-merge',
                        })
                    )
                    logger.warn('🤔', 'fold settled a source as failed; its merge did not happen', {
                        team_id: this.context.team.id,
                        source_distinct_id: sourceResult.sourceDistinctId,
                        target_distinct_id: request.targetDistinctId,
                        event_uuid: eventUuid,
                    })
                    break
                default:
                    break
            }
        }
        await Promise.all(warningAcks)
    }

    private emitIllegalDistinctIdWarning(
        illegalDistinctId: string,
        otherDistinctId: string,
        eventUuid: string
    ): Promise<void> {
        return emitIngestionWarning(this.context.outputs, this.context.team.id, {
            type: 'cannot_merge_with_illegal_distinct_id',
            details: {
                illegalDistinctId,
                otherDistinctId,
                distinctId: this.context.distinctId,
                eventUuid,
            },
            pipelineStep: 'person-merge',
            alwaysSend: true,
        }).then(() => undefined)
    }

    public getUpdateIsIdentified(): boolean {
        return this.context.updateIsIdentified
    }

    getContext(): PersonContext {
        return this.context
    }
}
