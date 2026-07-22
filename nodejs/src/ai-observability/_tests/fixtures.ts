import { randomUUID } from 'crypto'
import { DateTime } from 'luxon'

import { PostgresRouter } from '~/common/utils/db/postgres'
import { insertRow } from '~/tests/helpers/sql'

import { ClickHouseTimestamp, ProjectId, RawClickHouseEvent, Team } from '../../types'
import { LLMProviderKeyState, ProviderKey } from '../services/provider-key-manager.service'
import { Evaluation, EvaluationConditionSet, EvaluationStatus, Tagger } from '../types'

export const createEvaluation = (evaluation: Partial<Evaluation>): Evaluation => {
    const enabled = evaluation.enabled !== undefined ? evaluation.enabled : true
    const defaultStatus: EvaluationStatus = enabled ? 'active' : 'paused'
    return {
        id: randomUUID(),
        team_id: 1,
        name: 'Test Evaluation',
        enabled,
        status: defaultStatus,
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
        target: 'generation',
        target_config: {},
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

    const row = { ...created }
    delete row.provider_key_id

    const res = await insertRow(postgres, 'llm_analytics_evaluation', {
        ...row,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        created_by_id: 1001,
        deleted: false,
        description: created.description || '',
    })
    return res
}

export const createTagger = (tagger: Partial<Tagger> = {}): Tagger => {
    return {
        id: randomUUID(),
        team_id: 1,
        name: 'Test Tagger',
        enabled: tagger.enabled !== undefined ? tagger.enabled : true,
        tagger_type: 'llm',
        tagger_config: {
            prompt: 'Tag this',
            tags: [{ name: 'billing' }, { name: 'analytics' }],
            min_tags: 0,
            max_tags: 2,
        },
        conditions: [
            {
                id: 'condition-1',
                rollout_percentage: 100,
                properties: [],
            },
        ],
        created_at: DateTime.now().toISO(),
        updated_at: DateTime.now().toISO(),
        ...tagger,
    }
}

export const insertTagger = async (
    postgres: PostgresRouter,
    team_id: Team['id'],
    tagger: Partial<Tagger> = {}
): Promise<Tagger> => {
    const created = createTagger({
        ...tagger,
        team_id,
    })

    const row = { ...created }
    delete row.provider_key_id

    const res = await insertRow(postgres, 'llm_analytics_tagger', {
        ...row,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        created_by_id: 1001,
        deleted: false,
        description: created.description || '',
    })
    return res
}

export const insertProviderKey = async (
    postgres: PostgresRouter,
    team_id: Team['id'],
    providerKey: Partial<ProviderKey & { provider: string; name: string; error_message: string | null }> = {}
): Promise<ProviderKey> => {
    const created = {
        id: randomUUID(),
        team_id,
        provider: 'openai',
        name: 'Test provider key',
        state: 'ok' as LLMProviderKeyState,
        error_message: null,
        encrypted_config: { api_key: 'sk-test' },
        created_at: new Date().toISOString(),
        created_by_id: 1001,
        last_used_at: null,
        ...providerKey,
    }

    return await insertRow(postgres, 'llm_analytics_llmproviderkey', created)
}

export const insertModelConfiguration = async (
    postgres: PostgresRouter,
    team_id: Team['id'],
    modelConfiguration: Partial<{
        id: string
        provider: string
        model: string
        provider_key_id: string | null
    }> = {}
): Promise<{
    id: string
    team_id: Team['id']
    provider: string
    model: string
    provider_key_id: string | null
}> => {
    const created = {
        id: randomUUID(),
        team_id,
        provider: 'openai',
        model: 'gpt-5-mini',
        provider_key_id: null,
        created_at: new Date().toISOString(),
        ...modelConfiguration,
    }

    return await insertRow(postgres, 'llm_analytics_llmmodelconfiguration', created)
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
        historical_migration: false,
        ...data,
    }
}
