import { buildIntegerMatcher } from '~/common/config/config'
import { GroupPrescanFunction } from '~/ingestion/framework/builders'
import { PluginEvent } from '~/plugin-scaffold'
import { Team } from '~/types'

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
}

export interface MergeFoldOptions {
    PERSON_MERGE_FOLD_ENABLED: boolean
    PERSON_MERGE_FOLD_TEAM_ALLOWLIST: string
}

/** The fields of the pipeline item value the fold prescan reads and writes. */
export interface MergeFoldScanItem {
    event: PluginEvent
    team: Team
    mergeFoldPlan?: MergeFoldPlan
}

// Only $identify runs are folded. $create_alias/$merge_dangerously have
// different isMergeAllowed semantics per pair, and observed merge storms are
// walls of $identify events for one distinct_id.
function getFoldableAnonDistinctId(event: PluginEvent): string | null {
    if (event.event !== '$identify') {
        return null
    }
    const anonDistinctId = event.properties?.['$anon_distinct_id']
    if (anonDistinctId === undefined || anonDistinctId === null) {
        return null
    }
    return String(anonDistinctId)
}

/**
 * Build the group prescan that plans merge folds. Returns null when folding
 * is disabled so the pipeline is constructed without any prescan at all.
 *
 * Scans a group's queued chunk for consecutive runs of two or more foldable
 * $identify events (a single merge has nothing to fold). Each run gets one
 * shared MergeFoldPlan attached to the run's item values, with the distinct
 * anon ids as pairs (first event wins the pair's eventUuid; self-merges are
 * excluded). Fold size is naturally bounded by the batch size; pathological
 * per-source distinct_id counts are handled by the merge-mode limit pre-check
 * at execution time.
 */
export function createMergeFoldPrescan<T extends MergeFoldScanItem, C>(
    options: MergeFoldOptions
): GroupPrescanFunction<T, C> | null {
    if (!options.PERSON_MERGE_FOLD_ENABLED) {
        return null
    }
    const isTeamEnabled = buildIntegerMatcher(options.PERSON_MERGE_FOLD_TEAM_ALLOWLIST, true)

    return (items) => {
        if (items.length < 2 || !isTeamEnabled(items[0].value.team.id)) {
            return
        }

        let runStart = 0
        while (runStart < items.length) {
            if (getFoldableAnonDistinctId(items[runStart].value.event) === null) {
                runStart++
                continue
            }
            let runEnd = runStart + 1
            while (runEnd < items.length && getFoldableAnonDistinctId(items[runEnd].value.event) !== null) {
                runEnd++
            }
            if (runEnd - runStart >= 2) {
                planRun(items.slice(runStart, runEnd))
            }
            runStart = runEnd
        }
    }
}

function planRun<T extends MergeFoldScanItem>(run: { value: T }[]): void {
    const targetDistinctId = run[0].value.event.distinct_id
    const pairByAnonId = new Map<string, MergeFoldPair>()

    for (const item of run) {
        const anonDistinctId = getFoldableAnonDistinctId(item.value.event)
        if (anonDistinctId === null || anonDistinctId === targetDistinctId || pairByAnonId.has(anonDistinctId)) {
            continue
        }
        pairByAnonId.set(anonDistinctId, { anonDistinctId, eventUuid: item.value.event.uuid })
    }

    if (pairByAnonId.size === 0) {
        return
    }

    const plan: MergeFoldPlan = {
        targetDistinctId,
        pairs: [...pairByAnonId.values()],
        status: 'planned',
    }
    for (const item of run) {
        const anonDistinctId = getFoldableAnonDistinctId(item.value.event)
        if (anonDistinctId !== null && pairByAnonId.has(anonDistinctId)) {
            item.value.mergeFoldPlan = plan
        }
    }
}
