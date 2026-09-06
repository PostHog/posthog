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
    BillingAlertCheckNowResponseApi,
    BillingAlertConfigurationApi,
    BillingAlertDeleteDestinationApi,
    BillingAlertDestinationCreateDataApi,
    BillingAlertDestinationResponseApi,
    BillingAlertsEventsListParams,
    BillingAlertsListParams,
    BillingApi,
    BillingFeaturesApi,
    BillingForecastApi,
    BillingInvoicesApi,
    BillingInvoicesListParams,
    BillingLimitsApi,
    BillingOverviewResponseApi,
    BillingPeriodResponseApi,
    BillingProductApi,
    BillingProductsApi,
    BillingProductsListParams,
    BillingProductsRetrieveParams,
    BillingSpendRetrieveParams,
    BillingSpendSummaryApi,
    BillingSpendTimeseriesRetrieveParams,
    BillingSubscriptionApi,
    BillingTimeSeriesResponseApi,
    BillingUsageRetrieveParams,
    BillingUsageSummaryApi,
    BillingUsageTimeseriesRetrieveParams,
    PaginatedBillingAlertConfigurationListApi,
    PaginatedBillingAlertEventListApi,
    PaginatedBillingTimeSeriesPointListApi,
    PatchedBillingAlertConfigurationApi,
    PatchedBillingApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

export const getBillingListUrl = () => {
    return `/api/billing/`
}

export const billingList = async (options?: RequestInit): Promise<BillingOverviewResponseApi> => {
    return apiMutator<BillingOverviewResponseApi>(getBillingListUrl(), {
        ...options,
        method: 'GET',
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
    patchedBillingApi?: PatchedBillingApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBillingLicensePartialUpdateUrl(), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBillingApi),
    })
}

export const getBillingPeriodRetrieveUrl = () => {
    return `/api/billing/period/`
}

/**
 * @summary Get the current organization billing period
 */
export const billingPeriodRetrieve = async (options?: RequestInit): Promise<BillingPeriodResponseApi> => {
    return apiMutator<BillingPeriodResponseApi>(getBillingPeriodRetrieveUrl(), {
        ...options,
        method: 'GET',
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

export const getBillingSpendRetrieveUrl = (params?: BillingSpendRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0 ? `/api/billing/spend/?${stringifiedParams}` : `/api/billing/spend/`
}

/**
 * Endpoint to fetch spend data (proxy to billing service).
 */
export const billingSpendRetrieve = async (
    params?: BillingSpendRetrieveParams,
    options?: RequestInit
): Promise<BillingTimeSeriesResponseApi> => {
    return apiMutator<BillingTimeSeriesResponseApi>(getBillingSpendRetrieveUrl(params), {
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0 ? `/api/billing/usage/?${stringifiedParams}` : `/api/billing/usage/`
}

export const billingUsageRetrieve = async (
    params?: BillingUsageRetrieveParams,
    options?: RequestInit
): Promise<BillingTimeSeriesResponseApi> => {
    return apiMutator<BillingTimeSeriesResponseApi>(getBillingUsageRetrieveUrl(params), {
        ...options,
        method: 'GET',
    })
}

export const getBillingAlertsListUrl = (organizationId: string, params?: BillingAlertsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/billing/alerts/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/billing/alerts/`
}

export const billingAlertsList = async (
    organizationId: string,
    params?: BillingAlertsListParams,
    options?: RequestInit
): Promise<PaginatedBillingAlertConfigurationListApi> => {
    return apiMutator<PaginatedBillingAlertConfigurationListApi>(getBillingAlertsListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBillingAlertsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/billing/alerts/`
}

export const billingAlertsCreate = async (
    organizationId: string,
    billingAlertConfigurationApi: NonReadonly<BillingAlertConfigurationApi>,
    options?: RequestInit
): Promise<BillingAlertConfigurationApi> => {
    return apiMutator<BillingAlertConfigurationApi>(getBillingAlertsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingAlertConfigurationApi),
    })
}

export const getBillingAlertsRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/billing/alerts/${id}/`
}

export const billingAlertsRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<BillingAlertConfigurationApi> => {
    return apiMutator<BillingAlertConfigurationApi>(getBillingAlertsRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBillingAlertsUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/billing/alerts/${id}/`
}

export const billingAlertsUpdate = async (
    organizationId: string,
    id: string,
    billingAlertConfigurationApi: NonReadonly<BillingAlertConfigurationApi>,
    options?: RequestInit
): Promise<BillingAlertConfigurationApi> => {
    return apiMutator<BillingAlertConfigurationApi>(getBillingAlertsUpdateUrl(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingAlertConfigurationApi),
    })
}

export const getBillingAlertsPartialUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/billing/alerts/${id}/`
}

export const billingAlertsPartialUpdate = async (
    organizationId: string,
    id: string,
    patchedBillingAlertConfigurationApi?: NonReadonly<PatchedBillingAlertConfigurationApi>,
    options?: RequestInit
): Promise<BillingAlertConfigurationApi> => {
    return apiMutator<BillingAlertConfigurationApi>(getBillingAlertsPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBillingAlertConfigurationApi),
    })
}

export const getBillingAlertsDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/billing/alerts/${id}/`
}

export const billingAlertsDestroy = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBillingAlertsDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getBillingAlertsCheckNowCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/billing/alerts/${id}/check_now/`
}

/**
 * Evaluate this billing alert immediately against real billing spend data. An enabled alert can send notifications when the evaluation records a dispatchable event. A paused alert is evaluated as a preview only: it reports the current spend and would-be outcome without sending notifications or recording an evaluation.
 */
export const billingAlertsCheckNowCreate = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<BillingAlertCheckNowResponseApi> => {
    return apiMutator<BillingAlertCheckNowResponseApi>(getBillingAlertsCheckNowCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
    })
}

export const getBillingAlertsDestinationsCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/billing/alerts/${id}/destinations/`
}

/**
 * Create a notification destination for this alert. One HogFunction is created per alert event kind.
 */
export const billingAlertsDestinationsCreate = async (
    organizationId: string,
    id: string,
    billingAlertDestinationCreateDataApi: BillingAlertDestinationCreateDataApi,
    options?: RequestInit
): Promise<BillingAlertDestinationResponseApi> => {
    return apiMutator<BillingAlertDestinationResponseApi>(getBillingAlertsDestinationsCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingAlertDestinationCreateDataApi),
    })
}

export const getBillingAlertsDestinationsDeleteCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/billing/alerts/${id}/destinations/delete/`
}

/**
 * Delete a notification destination by deleting its HogFunction group atomically.
 */
export const billingAlertsDestinationsDeleteCreate = async (
    organizationId: string,
    id: string,
    billingAlertDeleteDestinationApi: BillingAlertDeleteDestinationApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBillingAlertsDestinationsDeleteCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingAlertDeleteDestinationApi),
    })
}

export const getBillingAlertsEventsListUrl = (
    organizationId: string,
    id: string,
    params?: BillingAlertsEventsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/billing/alerts/${id}/events/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/billing/alerts/${id}/events/`
}

/**
 * List evaluation and notification events for this billing alert, newest first.
 */
export const billingAlertsEventsList = async (
    organizationId: string,
    id: string,
    params?: BillingAlertsEventsListParams,
    options?: RequestInit
): Promise<PaginatedBillingAlertEventListApi> => {
    return apiMutator<PaginatedBillingAlertEventListApi>(getBillingAlertsEventsListUrl(organizationId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getBillingFeaturesRetrieveUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/billing/features/`
}

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get the features the organization's plans include
 */
export const billingFeaturesRetrieve = async (
    organizationId: string,
    options?: RequestInit
): Promise<BillingFeaturesApi> => {
    return apiMutator<BillingFeaturesApi>(getBillingFeaturesRetrieveUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}

export const getBillingForecastRetrieveUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/billing/forecast/`
}

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get the forecast for the rest of the billing period
 */
export const billingForecastRetrieve = async (
    organizationId: string,
    options?: RequestInit
): Promise<BillingForecastApi> => {
    return apiMutator<BillingForecastApi>(getBillingForecastRetrieveUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}

export const getBillingInvoicesListUrl = (organizationId: string, params?: BillingInvoicesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/billing/invoices/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/billing/invoices/`
}

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary List the organization's invoices
 */
export const billingInvoicesList = async (
    organizationId: string,
    params?: BillingInvoicesListParams,
    options?: RequestInit
): Promise<BillingInvoicesApi> => {
    return apiMutator<BillingInvoicesApi>(getBillingInvoicesListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBillingInvoicesContentRetrieveUrl = (organizationId: string, invoiceId: string) => {
    return `/api/organizations/${organizationId}/billing/invoices/${invoiceId}/content/`
}

/**
 * The invoice document, streamed from the billing provider by PostHog under the same access
 * check as the list. The provider's own link never reaches the client.
 * @summary Download an invoice as PDF
 */
export const billingInvoicesContentRetrieve = async (
    organizationId: string,
    invoiceId: string,
    options?: RequestInit
): Promise<Blob> => {
    return apiMutator<Blob>(getBillingInvoicesContentRetrieveUrl(organizationId, invoiceId), {
        ...options,
        method: 'GET',
    })
}

export const getBillingLimitsRetrieveUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/billing/limits/`
}

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get the organization's spend limits
 */
export const billingLimitsRetrieve = async (
    organizationId: string,
    options?: RequestInit
): Promise<BillingLimitsApi> => {
    return apiMutator<BillingLimitsApi>(getBillingLimitsRetrieveUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}

export const getBillingProductsListUrl = (organizationId: string, params?: BillingProductsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/billing/products/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/billing/products/`
}

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary List the organization's products
 */
export const billingProductsList = async (
    organizationId: string,
    params?: BillingProductsListParams,
    options?: RequestInit
): Promise<BillingProductsApi> => {
    return apiMutator<BillingProductsApi>(getBillingProductsListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBillingProductsRetrieveUrl = (
    organizationId: string,
    productKey: string,
    params?: BillingProductsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/billing/products/${productKey}/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/billing/products/${productKey}/`
}

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get one product
 */
export const billingProductsRetrieve = async (
    organizationId: string,
    productKey: string,
    params?: BillingProductsRetrieveParams,
    options?: RequestInit
): Promise<BillingProductApi> => {
    return apiMutator<BillingProductApi>(getBillingProductsRetrieveUrl(organizationId, productKey, params), {
        ...options,
        method: 'GET',
    })
}

export const getBillingSpendSummaryRetrieveUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/billing/spend/`
}

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get spend so far this billing period
 */
export const billingSpendSummaryRetrieve = async (
    organizationId: string,
    options?: RequestInit
): Promise<BillingSpendSummaryApi> => {
    return apiMutator<BillingSpendSummaryApi>(getBillingSpendSummaryRetrieveUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}

export const getBillingSpendTimeseriesRetrieveUrl = (
    organizationId: string,
    params?: BillingSpendTimeseriesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/billing/spend/timeseries/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/billing/spend/timeseries/`
}

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Spend over time
 */
export const billingSpendTimeseriesRetrieve = async (
    organizationId: string,
    params?: BillingSpendTimeseriesRetrieveParams,
    options?: RequestInit
): Promise<PaginatedBillingTimeSeriesPointListApi> => {
    return apiMutator<PaginatedBillingTimeSeriesPointListApi>(
        getBillingSpendTimeseriesRetrieveUrl(organizationId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getBillingSubscriptionRetrieveUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/billing/subscription/`
}

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get the organization's subscription
 */
export const billingSubscriptionRetrieve = async (
    organizationId: string,
    options?: RequestInit
): Promise<BillingSubscriptionApi> => {
    return apiMutator<BillingSubscriptionApi>(getBillingSubscriptionRetrieveUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}

export const getBillingUsageSummaryRetrieveUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/billing/usage/`
}

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get usage so far this billing period
 */
export const billingUsageSummaryRetrieve = async (
    organizationId: string,
    options?: RequestInit
): Promise<BillingUsageSummaryApi> => {
    return apiMutator<BillingUsageSummaryApi>(getBillingUsageSummaryRetrieveUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}

export const getBillingUsageTimeseriesRetrieveUrl = (
    organizationId: string,
    params?: BillingUsageTimeseriesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/billing/usage/timeseries/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/billing/usage/timeseries/`
}

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Usage over time
 */
export const billingUsageTimeseriesRetrieve = async (
    organizationId: string,
    params?: BillingUsageTimeseriesRetrieveParams,
    options?: RequestInit
): Promise<PaginatedBillingTimeSeriesPointListApi> => {
    return apiMutator<PaginatedBillingTimeSeriesPointListApi>(
        getBillingUsageTimeseriesRetrieveUrl(organizationId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}
