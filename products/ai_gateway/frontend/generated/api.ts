import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type { SpendLimitApi, SpendLimitWriteApi } from './api.schemas'

export const getAiGatewayUserSpendLimitRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/ai_gateway/@me/spend_limit/`
}

export const aiGatewayUserSpendLimitRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<SpendLimitApi> => {
    return apiMutator<SpendLimitApi>(getAiGatewayUserSpendLimitRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getAiGatewayUserSpendLimitCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/ai_gateway/@me/spend_limit/`
}

export const aiGatewayUserSpendLimitCreate = async (
    projectId: string,
    spendLimitWriteApi: SpendLimitWriteApi,
    options?: RequestInit
): Promise<SpendLimitApi> => {
    return apiMutator<SpendLimitApi>(getAiGatewayUserSpendLimitCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(spendLimitWriteApi),
    })
}

export const getAiGatewayUserSpendLimitClearUrl = (projectId: string) => {
    return `/api/projects/${projectId}/ai_gateway/@me/spend_limit/clear/`
}

export const aiGatewayUserSpendLimitClear = async (
    projectId: string,
    options?: RequestInit
): Promise<SpendLimitApi> => {
    return apiMutator<SpendLimitApi>(getAiGatewayUserSpendLimitClearUrl(projectId), {
        ...options,
        method: 'DELETE',
    })
}
