import type { ScoreDefinitionApi, ScoreDefinitionVersionApi } from '../generated/api.schemas'

export const historyDefinition: ScoreDefinitionApi = {
    id: 'quality-scorer',
    name: 'Answer quality',
    short_name: '',
    description: '',
    kind: 'numeric',
    calculation: 'reported',
    config: { min: 0, max: 10, passing_rule: { operator: 'gte', threshold: 8 } },
    composition: null,
    input_scorers: [],
    dependent_composite_count: 0,
    current_version: 2,
    current_version_id: 'quality-v2',
    archived: false,
    tags: [],
    team: 997,
    created_by: null,
    updated_by: null,
    created_at: '2026-01-01T12:00:00Z',
    updated_at: '2026-01-02T12:00:00Z',
}

export const historyVersions: ScoreDefinitionVersionApi[] = [
    {
        id: 'quality-v2',
        definition_id: historyDefinition.id,
        version: 2,
        kind: 'numeric',
        calculation: 'reported',
        composition: null,
        config: historyDefinition.config,
        created_at: '2026-01-02T12:00:00Z',
        created_by: null,
    },
    {
        id: 'quality-v1',
        definition_id: historyDefinition.id,
        version: 1,
        kind: 'numeric',
        calculation: 'reported',
        composition: null,
        config: { min: 0, max: 10, step: 1, passing_rule: { operator: 'gte', threshold: 7 } },
        created_at: historyDefinition.created_at,
        created_by: null,
    },
]
