import { buildIntegerMatcher } from '~/common/config/config'
import { decideProcessPerson, isDistinctIdIllegal } from '~/common/persons/person-utils'
import type { ChunkProcessingStep } from '~/ingestion/framework/base-chunk-pipeline'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import type { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, InternalPerson, Team } from '~/types'

/** One planned merge: an anon distinct_id to fold into the group's target distinct_id. */
export interface MergeFoldPair {
    anonDistinctId: string
    /** UUID of the first event in the run that asked for this pair. */
    eventUuid: string
}

/**
 * A fold plan shared by a consecutive run of $identify events in one
 * token:distinct_id group. The first event of the run executes all pairs in a
 * single merge operation; later events in the run find their pair satisfied
 * and skip the database entirely.
 *
 * - `planned`: not executed yet — the first merge event to reach the person
 *   step runs the folded merge.
 * - `executed`: the folded merge committed; events whose anon id is in
 *   `pairs` short-circuit.
 * - `abandoned`: the fold was skipped (limit pre-check) or failed after
 *   retries; every event processes individually through the sequential path.
 */
export interface MergeFoldPlan {
    targetDistinctId: string
    pairs: MergeFoldPair[]
    status: 'planned' | 'executed' | 'abandoned'
    /** The post-merge target person, set when the fold executes; later events in the run short-circuit to it. */
    mergedPerson?: InternalPerson
}

export interface MergeFoldOptions {
    PERSON_MERGE_FOLD_ENABLED: boolean
    PERSON_MERGE_FOLD_TEAM_ALLOWLIST: string
}

/** The fields of the pipeline item value the fold planning step reads. */
export interface MergeFoldScanItem {
    event: PluginEvent
    team: Team
    headers: EventHeaders
}

/**
 * The planning step's decision for one value:
 * - `planned`: the event is part of a fold run; the run's shared plan executes
 *   on its first event and the others short-circuit against it.
 * - `immediate`: no fold applies; the event processes individually right away,
 *   exactly as it would without folding.
 */
export type MergeFoldDecision = { type: 'planned'; plan: MergeFoldPlan } | { type: 'immediate' }

/** Attached to every value the planning step emits. */
export interface WithMergeFoldDecision {
    mergeFold: MergeFoldDecision
}

// Decisions carry no per-event state, so every immediate value shares one instance.
const IMMEDIATE: MergeFoldDecision = { type: 'immediate' }

/**
 * Per-item step for lanes where no merges can occur, and so nothing can fold:
 * decide `immediate` for every event so the person step's input is satisfied
 * without the lane's callers having to supply a decision.
 */
export function createImmediateMergeFoldStep<T>(): ProcessingStep<T, T & WithMergeFoldDecision> {
    return function immediateMergeFoldStep(value: T): Promise<PipelineResult<T & WithMergeFoldDecision>> {
        return Promise.resolve(ok({ ...value, mergeFold: IMMEDIATE }))
    }
}

// Only $identify runs are folded. $create_alias/$merge_dangerously have
// different isMergeAllowed semantics per pair, and observed merge storms are
// walls of $identify events for one distinct_id.
function getFoldableAnonDistinctId(item: MergeFoldScanItem): string | null {
    const event = item.event
    if (event.event !== '$identify') {
        return null
    }
    // A person-processing-disabled $identify never merges on the sequential
    // path (property false drops it, the force-disable header makes it
    // personless), so it must not contribute a pair to a fold either.
    if (!decideProcessPerson(event, item.headers).processPerson) {
        return null
    }
    const anonDistinctId = event.properties?.['$anon_distinct_id']
    if (anonDistinctId === undefined || anonDistinctId === null) {
        return null
    }
    return String(anonDistinctId)
}

/**
 * Build the group chunk step that decides, per value, whether the event folds
 * or processes immediately. The step is always wired; whether it plans
 * anything is its own decision, gated on the enabled flag and the team
 * allowlist, so disabled configurations emit every value as `immediate`.
 *
 * Scans a group's queued chunk for consecutive runs of two or more foldable
 * $identify events (a single merge has nothing to fold). Each run gets one
 * shared MergeFoldPlan, carried by the run's values as a `planned` decision,
 * with the distinct anon ids as pairs (first event wins the pair's eventUuid;
 * self-merges are excluded). Every other value gets the `immediate` decision.
 * Fold size is naturally bounded by the batch size; pathological per-source
 * distinct_id counts are handled by the merge-mode limit pre-check at
 * execution time.
 */
export function createMergeFoldPlanningStep<T extends MergeFoldScanItem>(
    options: MergeFoldOptions
): ChunkProcessingStep<T, T & WithMergeFoldDecision> {
    const isTeamEnabled = buildIntegerMatcher(options.PERSON_MERGE_FOLD_TEAM_ALLOWLIST, true)

    // Deliberately await-free: the single wrapping promise is the only
    // microtask this step adds to a group chunk.
    return function planMergeFolds(values: T[]): Promise<PipelineResult<T & WithMergeFoldDecision>[]> {
        const results = values.map((value) => ok({ ...value, mergeFold: IMMEDIATE }))
        if (!options.PERSON_MERGE_FOLD_ENABLED || values.length < 2 || !isTeamEnabled(values[0].team.id)) {
            return Promise.resolve(results)
        }

        let runStart = 0
        while (runStart < values.length) {
            if (getFoldableAnonDistinctId(values[runStart]) === null) {
                runStart++
                continue
            }
            let runEnd = runStart + 1
            while (runEnd < values.length && getFoldableAnonDistinctId(values[runEnd]) !== null) {
                runEnd++
            }
            if (runEnd - runStart >= 2) {
                planRun(values, results, runStart, runEnd)
            }
            runStart = runEnd
        }
        return Promise.resolve(results)
    }
}

function planRun<T extends MergeFoldScanItem>(
    values: T[],
    results: PipelineResult<T & WithMergeFoldDecision>[],
    runStart: number,
    runEnd: number
): void {
    const targetDistinctId = values[runStart].event.distinct_id
    const pairByAnonId = new Map<string, MergeFoldPair>()

    for (let index = runStart; index < runEnd; index++) {
        const anonDistinctId = getFoldableAnonDistinctId(values[index])
        if (anonDistinctId === null || anonDistinctId === targetDistinctId || pairByAnonId.has(anonDistinctId)) {
            continue
        }
        // An illegal anon id never merges; keeping its event on the immediate
        // path emits the per-event warning and keeps is_identified untouched,
        // exactly as today.
        if (isDistinctIdIllegal(anonDistinctId)) {
            continue
        }
        pairByAnonId.set(anonDistinctId, { anonDistinctId, eventUuid: values[index].event.uuid })
    }

    if (pairByAnonId.size === 0) {
        return
    }

    const plan: MergeFoldPlan = {
        targetDistinctId,
        pairs: [...pairByAnonId.values()],
        status: 'planned',
    }
    for (let index = runStart; index < runEnd; index++) {
        const anonDistinctId = getFoldableAnonDistinctId(values[index])
        if (anonDistinctId !== null && pairByAnonId.has(anonDistinctId)) {
            results[index] = ok({ ...values[index], mergeFold: { type: 'planned', plan } })
        }
    }
}
