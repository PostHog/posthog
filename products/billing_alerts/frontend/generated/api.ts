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
    BillingAlertCreateDestinationApi,
    BillingAlertDeleteDestinationApi,
    BillingAlertDestinationResponseApi,
    BillingAlertsEventsListParams,
    BillingAlertsListParams,
    PaginatedBillingAlertConfigurationListApi,
    PaginatedBillingAlertEventListApi,
    PatchedBillingAlertConfigurationApi,
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
 * Evaluate this billing alert immediately against real billing usage or spend data. Manual checks can send notifications when the evaluation records a dispatchable event.
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
    billingAlertCreateDestinationApi: BillingAlertCreateDestinationApi,
    options?: RequestInit
): Promise<BillingAlertDestinationResponseApi> => {
    return apiMutator<BillingAlertDestinationResponseApi>(getBillingAlertsDestinationsCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(billingAlertCreateDestinationApi),
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
