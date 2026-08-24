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
import type { UserSpendLimitApi, UserSpendLimitWriteApi } from './api.schemas'

export const getAiGatewayUserSpendLimitRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/ai_gateway/@me/spend_limit/`
}

/**
 * The requesting user's own spend limit for model traffic through the gateway.
 */
export const aiGatewayUserSpendLimitRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<UserSpendLimitApi[]> => {
    return apiMutator<UserSpendLimitApi[]>(getAiGatewayUserSpendLimitRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getAiGatewayUserSpendLimitCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/ai_gateway/@me/spend_limit/`
}

/**
 * The requesting user's own spend limit for model traffic through the gateway.
 */
export const aiGatewayUserSpendLimitCreate = async (
    projectId: string,
    userSpendLimitWriteApi: UserSpendLimitWriteApi,
    options?: RequestInit
): Promise<UserSpendLimitApi> => {
    return apiMutator<UserSpendLimitApi>(getAiGatewayUserSpendLimitCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userSpendLimitWriteApi),
    })
}

export const getAiGatewayUserSpendLimitClearUrl = (projectId: string) => {
    return `/api/projects/${projectId}/ai_gateway/@me/spend_limit/clear/`
}

/**
 * The requesting user's own spend limit for model traffic through the gateway.
 */
export const aiGatewayUserSpendLimitClear = async (
    projectId: string,
    options?: RequestInit
): Promise<UserSpendLimitApi> => {
    return apiMutator<UserSpendLimitApi>(getAiGatewayUserSpendLimitClearUrl(projectId), {
        ...options,
        method: 'DELETE',
    })
}
