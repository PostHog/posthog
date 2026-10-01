import type { OfflineExperimentReadApi, OfflineHistoryPointApi, ScoreDefinitionApi } from '../generated/api.schemas'

export const overviewScorers: ScoreDefinitionApi[] = ['Answer quality', 'Groundedness', 'Response time'].map(
    (name, index) => ({
        id: `11111111-1111-4111-8111-${String(index + 1).padStart(12, '0')}`,
        name,
        description: '',
        kind: index === 1 ? 'boolean' : 'numeric',
        archived: false,
        current_version: 2,
        current_version_id: `22222222-2222-4222-8222-${String(index + 1).padStart(12, '0')}`,
        config:
            index === 1
                ? { true_label: 'Grounded', false_label: 'Ungrounded' }
                : { min: 0, max: index === 2 ? 5000 : 1 },
        created_by: null,
        created_at: '2026-09-01T12:00:00Z',
        updated_at: '2026-09-20T12:00:00Z',
        team: 997,
    })
)

export const overviewExperiments: OfflineExperimentReadApi[] = Array.from({ length: 8 }, (_, index) => ({
    id: `33333333-3333-4333-8333-${String(index + 1).padStart(12, '0')}`,
    name: ['Support assistant prompt update', 'Tool selection regression', 'Response quality baseline'][index % 3],
    run_source: index % 3 === 0 ? 'ci' : index % 3 === 1 ? 'local' : null,
    status: index === 0 ? 'uploading' : index === 3 ? 'failed' : 'completed',
    started_at: `2026-09-${String(27 - index).padStart(2, '0')}T14:30:00Z`,
    created_at: `2026-09-${String(27 - index).padStart(2, '0')}T14:32:00Z`,
    finished_at: index === 0 ? null : `2026-09-${String(27 - index).padStart(2, '0')}T14:33:00Z`,
    expected_item_count: 100,
    expected_result_count: 300,
    accepted_item_count: index === 0 ? 60 : 100,
    visible_result_count: index === 0 ? 150 : 300,
    visible_scorer_definition_count: 3,
    visible_scorer_version_count: 3,
    result_count_scope: 'authorized',
    suite_key: null,
    dataset_source: null,
    dataset_identifier: null,
    dataset_revision_identifier: null,
    dataset_revision_id: null,
    application_version: 'app-v2',
    model_version: null,
    prompt_version: index < 4 ? 'prompt-v3' : 'prompt-v2',
}))

export function overviewHistory(scorer: ScoreDefinitionApi): OfflineHistoryPointApi[] {
    return overviewExperiments
        .filter((experiment) => experiment.status === 'completed')
        .map((experiment, index) => ({
            experiment,
            summary: {
                scorer: {
                    id: scorer.current_version_id!,
                    definition_id: scorer.id,
                    name: scorer.name,
                    description: '',
                    kind: scorer.kind,
                    archived: false,
                    version: 2,
                    config: scorer.config,
                },
                observed_item_count: 100,
                result_count: 100,
                status_counts: { ok: 95, error: 3, skipped: 2, not_applicable: 0 },
                missing_result_count: 0,
                distinct_case_count: 50,
                items_with_case_key_count: 100,
                items_without_case_key_count: 0,
                trial_item_count: 100,
                distinct_trial_count: 100,
                mean:
                    scorer.kind === 'numeric'
                        ? scorer.name === 'Response time'
                            ? 1400 + index * 90
                            : [0.64, 0.88, 0.9, 0.87, 0.92, 0.9][index]
                        : null,
                true_count: scorer.kind === 'boolean' ? 90 - index : null,
                false_count: scorer.kind === 'boolean' ? 5 + index : null,
                true_rate: scorer.kind === 'boolean' ? (90 - index) / 95 : null,
                categories: [],
            },
        }))
}
