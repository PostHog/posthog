import { randomUUID } from 'crypto'
import { DateTime } from 'luxon'

import { insertRow } from '~/tests/helpers/sql'

import { ClickHouseTimestamp, ProjectId, RawClickHouseEvent, Team } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { Evaluation, EvaluationConditionSet } from '../types'

export const createEvaluation = (evaluation: Partial<Evaluation>): Evaluation => {
    return {
        id: randomUUID(),
        team_id: 1,
        name: 'Test Evaluation',
        enabled: true,
        evaluation_type: 'llm_judge',
        evaluation_config: { prompt: 'Test prompt' },
        output_type: 'boolean',
        output_config: {},
        conditions: [
            {
                id: 'condition-1',
                rollout_percentage: 100,
                properties: [],
            },
        ],
        created_at: DateTime.now().toISO(),
        updated_at: DateTime.now().toISO(),
        ...evaluation,
    }
}

export const createEvaluationCondition = (overrides?: Partial<EvaluationConditionSet>): EvaluationConditionSet => {
    return {
        id: `condition-${randomUUID()}`,
        rollout_percentage: 100,
        properties: [],
        ...overrides,
    }
}

export const insertEvaluation = async (
    postgres: PostgresRouter,
    team_id: Team['id'],
    evaluation: Partial<Evaluation> = {}
): Promise<Evaluation> => {
    const created = createEvaluation({
        ...evaluation,
        team_id: team_id,
    })

    const res = await insertRow(postgres, 'llm_analytics_evaluation', {
        ...created,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        created_by_id: 1001,
        deleted: false,
        description: created.description || '',
    })
    return res
}

export const createAiGenerationEvent = (teamId: number, data: Partial<RawClickHouseEvent> = {}): RawClickHouseEvent => {
    return {
        team_id: teamId,
        project_id: teamId as ProjectId,
        created_at: new Date().toISOString() as ClickHouseTimestamp,
        elements_chain: '[]',
        person_created_at: new Date().toISOString() as ClickHouseTimestamp,
        person_properties: '{}',
        distinct_id: 'distinct_id_1',
        uuid: randomUUID(),
        event: '$ai_generation',
        timestamp: new Date().toISOString() as ClickHouseTimestamp,
        properties: JSON.stringify({
            $ai_model: 'gpt-4',
            $ai_input: ['test input'],
            $ai_output_choices: ['test output'],
        }),
        person_mode: 'full',
        ...data,
    }
}
