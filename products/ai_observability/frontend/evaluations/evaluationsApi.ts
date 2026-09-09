import type { AnyPropertyFilter } from '~/types'

import { evaluationsList, evaluationsPartialUpdate, llmAnalyticsEvaluationReportsList } from '../generated/api'
import type { EvaluationApi, EvaluationReportApi, PatchedEvaluationApi } from '../generated/api.schemas'
import { listAllPages } from '../listAllPages'
import type { EvaluationConfig, ModelConfiguration } from './types'

const EVALUATIONS_PAGE_SIZE = 100
const EVALUATION_REPORTS_PAGE_SIZE = 100

function isPropertyFilter(value: unknown): value is AnyPropertyFilter {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function modelConfigurationFromApi(evaluation: EvaluationApi): ModelConfiguration | null {
    if (!evaluation.model_configuration) {
        return null
    }

    return {
        provider: evaluation.model_configuration.provider,
        model: evaluation.model_configuration.model,
        provider_key_id: evaluation.model_configuration.provider_key_id ?? null,
        provider_key_name: evaluation.model_configuration.provider_key_name,
    }
}

export function evaluationFromApi(evaluation: EvaluationApi): EvaluationConfig {
    const baseEvaluation = {
        id: evaluation.id,
        name: evaluation.name,
        description: evaluation.description,
        directory_id: evaluation.directory_id ?? null,
        enabled: evaluation.enabled ?? false,
        status: evaluation.status,
        status_reason: evaluation.status_reason,
        status_reason_detail: evaluation.status_reason_detail,
        output_config: evaluation.output_config ?? {},
        conditions: (evaluation.conditions ?? []).map((condition) => ({
            id: condition.id,
            rollout_percentage: condition.rollout_percentage,
            properties: (condition.properties ?? []).filter(isPropertyFilter),
        })),
        target: evaluation.target ?? 'generation',
        target_config: evaluation.target_config ?? {},
        model_configuration: modelConfigurationFromApi(evaluation),
        created_at: evaluation.created_at,
        updated_at: evaluation.updated_at,
        created_by: evaluation.created_by
            ? {
                  id: evaluation.created_by.id,
                  uuid: evaluation.created_by.uuid,
                  distinct_id: evaluation.created_by.distinct_id ?? '',
                  first_name: evaluation.created_by.first_name ?? '',
                  last_name: evaluation.created_by.last_name,
                  email: evaluation.created_by.email,
                  is_email_verified: evaluation.created_by.is_email_verified,
                  role_at_organization: evaluation.created_by.role_at_organization,
              }
            : null,
        deleted: evaluation.deleted,
    }

    if (
        evaluation.evaluation_type === 'llm_judge' &&
        evaluation.output_type === 'boolean' &&
        evaluation.evaluation_config &&
        'prompt' in evaluation.evaluation_config
    ) {
        return {
            ...baseEvaluation,
            evaluation_type: 'llm_judge',
            output_type: 'boolean',
            evaluation_config: { prompt: evaluation.evaluation_config.prompt },
        }
    }

    if (
        evaluation.evaluation_type === 'hog' &&
        evaluation.output_type === 'boolean' &&
        evaluation.evaluation_config &&
        'source' in evaluation.evaluation_config &&
        typeof evaluation.evaluation_config.source === 'string'
    ) {
        return {
            ...baseEvaluation,
            evaluation_type: 'hog',
            output_type: 'boolean',
            evaluation_config: { source: evaluation.evaluation_config.source },
        }
    }

    if (evaluation.evaluation_type === 'sentiment' && evaluation.output_type === 'sentiment') {
        return {
            ...baseEvaluation,
            evaluation_type: 'sentiment',
            output_type: 'sentiment',
            evaluation_config: { source: 'user_messages' },
            model_configuration: null,
        }
    }

    throw new Error(`Evaluation ${evaluation.id} has an invalid type or configuration`)
}

export async function listAllEvaluations(projectId: string): Promise<EvaluationConfig[]> {
    const evaluations = await listAllPages((offset) =>
        evaluationsList(projectId, { limit: EVALUATIONS_PAGE_SIZE, offset })
    )
    return evaluations.map(evaluationFromApi)
}

export async function listAllEvaluationReports(projectId: string): Promise<EvaluationReportApi[]> {
    return listAllPages((offset) =>
        llmAnalyticsEvaluationReportsList(projectId, {
            limit: EVALUATION_REPORTS_PAGE_SIZE,
            offset,
        })
    )
}

export async function patchEvaluation(
    projectId: string,
    evaluationId: string,
    update: PatchedEvaluationApi
): Promise<EvaluationConfig> {
    return evaluationFromApi(await evaluationsPartialUpdate(projectId, evaluationId, update))
}
