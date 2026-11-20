import { AutoresearchPipelineApi } from './generated/api.schemas'
import { modelQuality } from './modelQuality'
import { eventLabel } from './pipelineQuestion'

export type ModelListSort = 'created' | 'attention' | 'name'

export const MODEL_LIST_SORT_OPTIONS: { value: ModelListSort; label: string }[] = [
    { value: 'created', label: 'Recently created' },
    { value: 'attention', label: 'Needs attention' },
    { value: 'name', label: 'Name' },
]

type ListedPipeline = Pick<
    AutoresearchPipelineApi,
    | 'name'
    | 'target_event'
    | 'status'
    | 'created_at'
    | 'not_promoted_reason'
    | 'live_training_run'
    | 'champion_holdout_auc'
    | 'champion_realized_auc'
    | 'champion_lift_at_10'
    | 'champion_is_preliminary'
>

/** Not live and not training toward it ranks first, then a weak model, then the rest. */
function attentionRank(pipeline: ListedPipeline): number {
    const training = !!pipeline.live_training_run
    if (!training && (!!pipeline.not_promoted_reason || pipeline.status === 'paused' || pipeline.status === 'draft')) {
        return 0
    }
    const quality = modelQuality({
        holdoutAuc: pipeline.champion_holdout_auc,
        realizedAuc: pipeline.champion_realized_auc,
        liftAt10: pipeline.champion_lift_at_10,
        isPreliminary: pipeline.champion_is_preliminary,
        target: pipeline.target_event,
    })
    return quality?.verdict === 'Weak' ? 1 : 2
}

function newestFirst(a: ListedPipeline, b: ListedPipeline): number {
    return b.created_at.localeCompare(a.created_at)
}

/** Matches the search against the model name, the raw target event, and the event's display name. */
export function matchesSearch(pipeline: ListedPipeline, search: string): boolean {
    const term = search.trim().toLowerCase()
    if (!term) {
        return true
    }
    return [pipeline.name, pipeline.target_event, eventLabel(pipeline.target_event)].some((text) =>
        text.toLowerCase().includes(term)
    )
}

export function filterAndSortPipelines<T extends ListedPipeline>(
    pipelines: T[],
    search: string,
    sort: ModelListSort
): T[] {
    const matching = pipelines.filter((pipeline) => matchesSearch(pipeline, search))
    switch (sort) {
        case 'name':
            return matching.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }))
        case 'attention':
            return matching.sort((a, b) => attentionRank(a) - attentionRank(b) || newestFirst(a, b))
        default:
            return matching.sort(newestFirst)
    }
}
