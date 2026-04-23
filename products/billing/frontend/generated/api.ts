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
import type {
    BillingApi,
    BillingListParams,
    BillingSpendRetrieveParams,
    BillingUsageRetrieveParams,
    PaginatedBillingListApi,
    PatchedBillingApi,
} from './api.schemas'

export const getBillingListUrl = (params?: BillingListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0 ? `/api/billing/?${stringifiedParams}` : `/api/billing/`
}

export const billingList = async (
    params?: BillingListParams,
    options?: RequestInit
): Promise<PaginatedBillingListApi> => {
    return apiMutator<PaginatedBillingListApi>(getBillingListUrl(params), {
        ...options,
        method: 'GET',
    })
}

export const getBillingPartialUpdateUrl = () => {
    return `/api/billing///`
}

export const billingPartialUpdate = async (
    patchedBillingApi: PatchedBillingApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBillingPartialUpdateUrl(), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBillingApi),
    })
}

export const getBillingActivateCreateUrl = () => {
    return `/api/billing/activate/`
}

export const billingActivateCreate = async (billingApi: BillingApi, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBillingActivateCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingApi),
    })
}

export const getBillingActivateAuthorizeCreateUrl = () => {
    return `/api/billing/activate/authorize/`
}

export const billingActivateAuthorizeCreate = async (billingApi: BillingApi, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBillingActivateAuthorizeCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingApi),
    })
}

export const getBillingActivateAuthorizeStatusCreateUrl = () => {
    return `/api/billing/activate/authorize/status/`
}

export const billingActivateAuthorizeStatusCreate = async (
    billingApi: BillingApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBillingActivateAuthorizeStatusCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingApi),
    })
}

export const getBillingCouponsClaimCreateUrl = () => {
    return `/api/billing/coupons/claim/`
}

export const billingCouponsClaimCreate = async (billingApi: BillingApi, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBillingCouponsClaimCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingApi),
    })
}

export const getBillingCouponsOverviewRetrieveUrl = () => {
    return `/api/billing/coupons/overview/`
}

export const billingCouponsOverviewRetrieve = async (options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBillingCouponsOverviewRetrieveUrl(), {
        ...options,
        method: 'GET',
    })
}

export const getBillingCreditsOverviewRetrieveUrl = () => {
    return `/api/billing/credits/overview/`
}

export const billingCreditsOverviewRetrieve = async (options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBillingCreditsOverviewRetrieveUrl(), {
        ...options,
        method: 'GET',
    })
}

export const getBillingCreditsPurchaseCreateUrl = () => {
    return `/api/billing/credits/purchase/`
}

export const billingCreditsPurchaseCreate = async (billingApi: BillingApi, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBillingCreditsPurchaseCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingApi),
    })
}

export const getBillingDeactivateCreateUrl = () => {
    return `/api/billing/deactivate/`
}

export const billingDeactivateCreate = async (billingApi: BillingApi, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBillingDeactivateCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingApi),
    })
}

export const getBillingGetInvoicesRetrieveUrl = () => {
    return `/api/billing/get_invoices/`
}

export const billingGetInvoicesRetrieve = async (options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBillingGetInvoicesRetrieveUrl(), {
        ...options,
        method: 'GET',
    })
}

export const getBillingLicensePartialUpdateUrl = () => {
    return `/api/billing/license/`
}

export const billingLicensePartialUpdate = async (
    patchedBillingApi: PatchedBillingApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBillingLicensePartialUpdateUrl(), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBillingApi),
    })
}

export const getBillingPortalRetrieveUrl = () => {
    return `/api/billing/portal/`
}

export const billingPortalRetrieve = async (options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBillingPortalRetrieveUrl(), {
        ...options,
        method: 'GET',
    })
}

/**
 * Endpoint to fetch spend data (proxy to billing service).
 */
export const getBillingSpendRetrieveUrl = (params?: BillingSpendRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0 ? `/api/billing/spend/?${stringifiedParams}` : `/api/billing/spend/`
}

export const billingSpendRetrieve = async (
    params?: BillingSpendRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBillingSpendRetrieveUrl(params), {
        ...options,
        method: 'GET',
    })
}

export const getBillingStartupsApplyCreateUrl = () => {
    return `/api/billing/startups/apply/`
}

export const billingStartupsApplyCreate = async (billingApi: BillingApi, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBillingStartupsApplyCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingApi),
    })
}

export const getBillingSubscriptionSwitchPlanCreateUrl = () => {
    return `/api/billing/subscription/switch-plan/`
}

export const billingSubscriptionSwitchPlanCreate = async (
    billingApi: BillingApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBillingSubscriptionSwitchPlanCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingApi),
    })
}

export const getBillingTrialsActivateCreateUrl = () => {
    return `/api/billing/trials/activate/`
}

export const billingTrialsActivateCreate = async (billingApi: BillingApi, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBillingTrialsActivateCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingApi),
    })
}

export const getBillingTrialsCancelCreateUrl = () => {
    return `/api/billing/trials/cancel/`
}

export const billingTrialsCancelCreate = async (billingApi: BillingApi, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getBillingTrialsCancelCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingApi),
    })
}

export const getBillingUsageRetrieveUrl = (params?: BillingUsageRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0 ? `/api/billing/usage/?${stringifiedParams}` : `/api/billing/usage/`
}

export const billingUsageRetrieve = async (
    params?: BillingUsageRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBillingUsageRetrieveUrl(params), {
        ...options,
        method: 'GET',
    })
}
