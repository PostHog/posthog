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
import type { OpenFgaStatusApi } from './api.schemas'

export const getAuthzStatusRetrieveUrl = () => {
    return `/api/authz/status/`
}

/**
 * Return whether OpenFGA is reachable, and the store and authorization model that authz uses.
 */
export const authzStatusRetrieve = async (options?: RequestInit): Promise<OpenFgaStatusApi> => {
    return apiMutator<OpenFgaStatusApi>(getAuthzStatusRetrieveUrl(), {
        ...options,
        method: 'GET',
    })
}
