import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { isDistinctIdIllegal } from '~/common/persons/person-utils'
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
    PersonMergeLimitExceededError,
    PersonMergeResult,
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
})

export const mergeFoldFallbackCounter = new Counter({
    name: 'person_merge_fold_fallback_total',
    help: 'Number of merge folds abandoned in favor of the sequential path.',
    labelNames: ['reason'],
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
                await emitIngestionWarning(this.context.outputs, this.context.team.id, {
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
                })
                logger.warn('🤔', 'merge dropped: person claimed by a concurrent lifecycle operation', {
                    team_id: this.context.team.id,
                    distinctId: this.context.distinctId,
                })
                return mergeSuccess(undefined, Promise.resolve(), true)
            }
            captureException(e, {
                tags: { team_id: this.context.team.id, pipeline_step: 'processPersonsStep' },
                extra: {
                    location: 'handleIdentifyOrAlias',
                    distinctId: this.context.distinctId,
                    anonId: String(this.context.eventProperties['$anon_distinct_id']),
                    alias: String(this.context.eventProperties['alias']),
                },
            })
            mergeFinalFailuresCounter.inc()
            logger.error('handleIdentifyOrAlias failed', {
                error: e,
                team_id: this.context.team.id,
                distinctId: this.context.distinctId,
                event_name: this.context.event.event,
                anon_distinct_id: String(this.context.eventProperties['$anon_distinct_id']),
                alias: String(this.context.eventProperties['alias']),
            })
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
        if (isDistinctIdIllegal(mergeIntoDistinctId)) {
            await this.emitIllegalDistinctIdWarning(mergeIntoDistinctId, otherPersonDistinctId, this.context.event.uuid)
            return mergeSuccess(undefined, Promise.resolve(), true)
        }
        if (isDistinctIdIllegal(otherPersonDistinctId)) {
            await this.emitIllegalDistinctIdWarning(otherPersonDistinctId, mergeIntoDistinctId, this.context.event.uuid)
            return mergeSuccess(undefined, Promise.resolve(), true)
        }

        this.context.updateIsIdentified = true
        const request = this.buildRequest(
            mergeIntoDistinctId,
            [{ distinctId: otherPersonDistinctId, eventUuid: this.context.event.uuid }],
            timestamp
        )
        // The store owns the whole merge; retryable conflicts re-enter
        // here with fresh state. The Postgres merge surfaces them as
        // throws; the saga answers a settled skipped_conflict, which it
        // re-classifies on every call rather than recording, so converting
        // it into a throw gives both worlds the same retry budget before
        // the claim-dropped path.
        const result = await promiseRetry(async () => {
            const attempt = await this.context.personStore.mergePersons(request)
            if (attempt.results[0]?.outcome === 'skipped_conflict') {
                throw new PersonClaimedByLifecycleOpError(
                    'merge saga: a live lifecycle operation holds a person in this merge',
                    this.context.team.id
                )
            }
            return attempt
        }, 'merge_distinct_ids')
        return await this.mapSingleSourceResult(result, otherPersonDistinctId, mergeIntoDistinctId)
    }

    /**
     * One request for either world, single-source or folded. The event
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
            opId: this.context.event.uuid,
            allowIdentifiedSources: this.context.event.event === '$merge_dangerously',
            mergeMode: this.context.mergeMode,
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

        if (isDistinctIdIllegal(plan.targetDistinctId)) {
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
            // Any failure falls back to the sequential path: the current event
            // re-runs its own merge (a no-op if the fold partially landed), and
            // later events in the run process individually with full retries.
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

        plan.status = 'executed'
        plan.mergedPerson = result.survivor
        try {
            await this.emitFoldWarnings(result.results, request)
        } catch (error) {
            // Warnings are diagnostics; a committed fold must still return
            // its result and ack.
            logger.warn('🤔', 'fold warning emission failed', { team_id: this.context.team.id, error })
        }
        return mergeSuccess(result.survivor, result.kafkaAck ?? Promise.resolve(), true)
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
    private async mapSingleSourceResult(
        result: MergePersonsResult,
        otherPersonDistinctId: string,
        mergeIntoDistinctId: string
    ): Promise<PersonMergeResult> {
        const sourceResult = result.results[0]
        // A verdict for a different source than the one requested means the
        // idempotency key replayed against a differently shaped request;
        // treat it as a failure rather than mis-attribute the outcome.
        const outcome =
            sourceResult === undefined || sourceResult.sourceDistinctId !== otherPersonDistinctId
                ? 'error'
                : sourceResult.outcome
        const survivor = result.survivor ?? undefined
        const kafkaAck = result.kafkaAck ?? Promise.resolve()
        switch (outcome) {
            case 'merged':
            case 'attached':
            case 'noop_same_person':
                return mergeSuccess(survivor, kafkaAck, result.survivorNeedsUpdate ?? true)
            case 'skipped_already_identified':
                await emitIngestionWarning(this.context.outputs, this.context.team.id, {
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
                return mergeSuccess(survivor, kafkaAck, true)
            case 'skipped_illegal':
                // Both ids are pre-checked in merge(); the saga's own list
                // can be wider, so honor its verdict with the same warning.
                await this.emitIllegalDistinctIdWarning(
                    otherPersonDistinctId,
                    mergeIntoDistinctId,
                    this.context.event.uuid
                )
                return mergeSuccess(survivor, kafkaAck, true)
            case 'skipped_race':
                // A concurrent merge kept winning the persons through every
                // retry; the merge drops and the target stays the survivor.
                await emitIngestionWarning(this.context.outputs, this.context.team.id, {
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
                return mergeSuccess(survivor, kafkaAck, true)
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
            case 'error':
            default:
                throw new Error(
                    `merge failed for team ${this.context.team.id} (outcome ${outcome}); see the merge world's logs`
                )
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
        for (const sourceResult of results) {
            const eventUuid = eventUuidBySource.get(sourceResult.sourceDistinctId) ?? this.context.event.uuid
            switch (sourceResult.outcome) {
                case 'skipped_already_identified':
                    await emitIngestionWarning(this.context.outputs, this.context.team.id, {
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
                    break
                case 'skipped_illegal':
                    await this.emitIllegalDistinctIdWarning(
                        sourceResult.sourceDistinctId,
                        request.targetDistinctId,
                        eventUuid
                    )
                    break
                case 'skipped_conflict':
                case 'skipped_race':
                    await emitIngestionWarning(this.context.outputs, this.context.team.id, {
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
                    break
                case 'skipped_move_limit':
                    // Only the saga can answer this inside an executed fold;
                    // the Postgres merge aborts the whole fold instead so each
                    // event gets its own over-limit policy decision. Temporary
                    // while personhog mode is a testing path: the skipped
                    // source's merge is lost, logged here for visibility. The
                    // permanent fix is saga-side chunked moves.
                    logger.warn('🤔', 'fold skipped an over-limit source; its merge is dropped', {
                        team_id: this.context.team.id,
                        source_distinct_id: sourceResult.sourceDistinctId,
                        target_distinct_id: request.targetDistinctId,
                    })
                    break
                default:
                    break
            }
        }
    }

    private async emitIllegalDistinctIdWarning(
        illegalDistinctId: string,
        otherDistinctId: string,
        eventUuid: string
    ): Promise<void> {
        await emitIngestionWarning(this.context.outputs, this.context.team.id, {
            type: 'cannot_merge_with_illegal_distinct_id',
            details: {
                illegalDistinctId,
                otherDistinctId,
                distinctId: this.context.distinctId,
                eventUuid,
            },
            pipelineStep: 'person-merge',
            alwaysSend: true,
        })
    }

    public getUpdateIsIdentified(): boolean {
        return this.context.updateIsIdentified
    }

    getContext(): PersonContext {
        return this.context
    }
}
