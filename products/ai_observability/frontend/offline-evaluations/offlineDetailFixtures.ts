import type {
    OfflineExperimentReadApi,
    OfflineItemReadApi,
    OfflineResultCellsApi,
    OfflineResultReadApi,
    OfflineScorerSummaryApi,
} from '../generated/api.schemas'
import { overviewExperiments, overviewHistory, overviewScorers } from './offlineOverviewFixtures'

export const detailExperiment: OfflineExperimentReadApi = {
    ...overviewExperiments[0],
    name: 'Answer quality benchmark',
    accepted_item_count: 8,
    expected_item_count: 8,
    visible_result_count: 200,
    expected_result_count: 200,
    visible_scorer_definition_count: 25,
    visible_scorer_version_count: 25,
}

export function makeOfflineDetailSummaries(count: number): OfflineScorerSummaryApi[] {
    return Array.from({ length: count }, (_, index) => {
        const base = overviewHistory(overviewScorers[index % 3])[0].summary
        return {
            ...base,
            observed_item_count: 8,
            result_count: 8,
            status_counts: { ok: 7, error: 1, skipped: 0, not_applicable: 0 },
            pass_count: 5,
            fail_count: 2,
            pass_rate: 5 / 7,
            missing_result_count: 0,
            scorer: {
                ...base.scorer,
                id: `22222222-2222-4222-8222-${String(index + 1).padStart(12, '0')}`,
                definition_id: `11111111-1111-4111-8111-${String(index + 1).padStart(12, '0')}`,
                name: index < 3 ? base.scorer.name : `Rubric ${index + 1}`,
            },
        }
    })
}

export const detailSummaries = makeOfflineDetailSummaries(25)
export const detailItems: OfflineItemReadApi[] = Array.from({ length: 8 }, (_, index) => ({
    id: `44444444-4444-4444-8444-${String(index + 1).padStart(12, '0')}`,
    experiment_id: detailExperiment.id,
    case_key: `question-${index + 1}`,
    trial: index > 3 ? '2' : '1',
    dataset_item_identifier: null,
    dataset_item_version_identifier: null,
    dataset_item_version_id: null,
    application_trace_id: null,
    accepted_at: detailExperiment.created_at,
    payload_state: 'available',
    payload_expires_at: null,
    results: [],
}))

export function makeOfflineDetailCells(itemIds: string[], versionIds: string[]): OfflineResultCellsApi {
    const scorerVersions = detailSummaries
        .filter((summary) => versionIds.includes(summary.scorer.id))
        .map((summary) => summary.scorer)
    return {
        scorer_versions: scorerVersions,
        results: itemIds.flatMap((itemId) => {
            const itemIndex = Math.max(
                0,
                detailItems.findIndex((item) => item.id === itemId)
            )
            return scorerVersions.map((scorer) => ({
                id: `55555555-5555-4555-8555-${String(itemIndex * 1000 + detailSummaries.findIndex((summary) => summary.scorer.id === scorer.id) + 1).padStart(12, '0')}`,
                item_id: itemId,
                scorer_version_id: scorer.id,
                status:
                    itemIndex === 3 && scorer.id === detailSummaries[0].scorer.id
                        ? ('error' as const)
                        : ('ok' as const),
                value:
                    itemIndex === 3 && scorer.id === detailSummaries[0].scorer.id
                        ? null
                        : scorer.kind === 'boolean'
                          ? itemIndex % 3 !== 0
                          : 'max' in scorer.config && scorer.config.max! > 1
                            ? 1400 + itemIndex * 150
                            : 0.65 + itemIndex * 0.05,
                error_code: itemIndex === 3 && scorer.id === detailSummaries[0].scorer.id ? 'evaluator_timeout' : null,
                evaluator_trace_id: null,
                evaluated_at: null,
                accepted_at: detailExperiment.created_at,
                payload_state: 'available' as const,
                payload_expires_at: null,
            }))
        }),
    }
}

export function offlineDetailItemResults(itemId: string): OfflineResultReadApi[] {
    const cells = makeOfflineDetailCells(
        [itemId],
        detailSummaries.map((summary) => summary.scorer.id)
    )
    return cells.results.map(({ scorer_version_id, ...result }) => ({
        ...result,
        scorer: cells.scorer_versions.find((scorer) => scorer.id === scorer_version_id)!,
    }))
}
