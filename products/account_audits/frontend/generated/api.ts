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
import type { AccountAuditStartRequestApi, AccountAuditStartResponseApi } from './api.schemas'

export const getAccountAuditsStartCreateUrl = () => {
    return `/api/account_audits/start/`
}

export const accountAuditsStartCreate = async (
    accountAuditStartRequestApi: AccountAuditStartRequestApi,
    options?: RequestInit
): Promise<AccountAuditStartResponseApi | void> => {
    return apiMutator<AccountAuditStartResponseApi | void>(getAccountAuditsStartCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(accountAuditStartRequestApi),
    })
}
