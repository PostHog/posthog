import type { OfflineHistoryPointApi, ScoreDefinitionApi, ScoreDefinitionVersionApi } from '../generated/api.schemas'

export const OFFLINE_STORY_DEFINITION: ScoreDefinitionApi = {
    id: '10000000-0000-4000-8000-000000000001',
    name: 'Answer relevance',
    description: 'Relevance to the question, scored from 0 to 5.',
    kind: 'numeric',
    archived: false,
    current_version: 2,
    current_version_id: '20000000-0000-4000-8000-000000000002',
    config: { min: 0, max: 5 },
    created_by: null,
    created_at: '2026-01-01T10:00:00Z',
    updated_at: null,
    team: 1,
}

export const OFFLINE_STORY_VERSION: ScoreDefinitionVersionApi = {
    id: OFFLINE_STORY_DEFINITION.current_version_id!,
    definition_id: OFFLINE_STORY_DEFINITION.id,
    version: 2,
    kind: 'numeric',
    config: OFFLINE_STORY_DEFINITION.config,
    created_at: '2026-01-01T10:00:00Z',
    created_by: null,
}

export function makeOfflineHistoryPoint(index: number, mean: number | null = 4.2): OfflineHistoryPointApi {
    return {
        experiment: {
            id: `30000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
            name: `Answer evaluation ${index}`,
            run_source: index % 2 === 0 ? 'ci' : 'local',
            status: 'completed',
            started_at: `2026-01-${String(index).padStart(2, '0')}T10:00:00Z`,
            created_at: '2026-01-20T12:00:00Z',
            finished_at: '2026-01-20T12:05:00Z',
            expected_item_count: 100,
            expected_result_count: null,
            accepted_item_count: 100,
            visible_result_count: 97,
            visible_scorer_definition_count: 1,
            visible_scorer_version_count: 1,
            result_count_scope: 'authorized',
            suite_key: 'answer-checks',
            dataset_source: null,
            dataset_identifier: null,
            dataset_revision_identifier: null,
            dataset_revision_id: null,
            application_version: 'example-revision',
            model_version: 'example-model',
            prompt_version: 'prompt-v2',
        },
        summary: {
            scorer: {
                id: OFFLINE_STORY_VERSION.id,
                definition_id: OFFLINE_STORY_DEFINITION.id,
                version: 2,
                kind: 'numeric',
                name: OFFLINE_STORY_DEFINITION.name,
                description: OFFLINE_STORY_DEFINITION.description,
                archived: false,
                config: OFFLINE_STORY_DEFINITION.config,
            },
            observed_item_count: 100,
            result_count: 97,
            status_counts: { ok: mean === null ? 0 : 92, error: mean === null ? 94 : 2, skipped: 2, not_applicable: 1 },
            missing_result_count: 3,
            distinct_case_count: 50,
            items_with_case_key_count: 100,
            items_without_case_key_count: 0,
            trial_item_count: 100,
            distinct_trial_count: 100,
            mean,
            true_count: null,
            false_count: null,
            true_rate: null,
            categories: [],
        },
    }
}

export const OFFLINE_STORY_POINTS = [4.3, 4.1, 4.4, 4.2, 3.2, 3.0, 4.0, 4.2].map((mean, index) =>
    makeOfflineHistoryPoint(index + 1, mean)
)
