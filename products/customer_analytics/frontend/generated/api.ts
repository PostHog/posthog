/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
import type {
    CustomerProfileConfigApi,
    EnvironmentsCustomerProfileConfigsListParams,
    PaginatedCustomerProfileConfigListApi,
    PatchedCustomerProfileConfigApi,
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

export type environmentsCustomerProfileConfigsListResponse200 = {
    data: PaginatedCustomerProfileConfigListApi
    status: 200
}

export type environmentsCustomerProfileConfigsListResponseSuccess =
    environmentsCustomerProfileConfigsListResponse200 & {
        headers: Headers
    }
export type environmentsCustomerProfileConfigsListResponse = environmentsCustomerProfileConfigsListResponseSuccess

export const getEnvironmentsCustomerProfileConfigsListUrl = (
    projectId: string,
    params?: EnvironmentsCustomerProfileConfigsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/customer_profile_configs/?${stringifiedParams}`
        : `/api/environments/${projectId}/customer_profile_configs/`
}

export const environmentsCustomerProfileConfigsList = async (
    projectId: string,
    params?: EnvironmentsCustomerProfileConfigsListParams,
    options?: RequestInit
): Promise<environmentsCustomerProfileConfigsListResponse> => {
    return apiMutator<environmentsCustomerProfileConfigsListResponse>(
        getEnvironmentsCustomerProfileConfigsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsCustomerProfileConfigsCreateResponse201 = {
    data: CustomerProfileConfigApi
    status: 201
}

export type environmentsCustomerProfileConfigsCreateResponseSuccess =
    environmentsCustomerProfileConfigsCreateResponse201 & {
        headers: Headers
    }
export type environmentsCustomerProfileConfigsCreateResponse = environmentsCustomerProfileConfigsCreateResponseSuccess

export const getEnvironmentsCustomerProfileConfigsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/customer_profile_configs/`
}

export const environmentsCustomerProfileConfigsCreate = async (
    projectId: string,
    customerProfileConfigApi: NonReadonly<CustomerProfileConfigApi>,
    options?: RequestInit
): Promise<environmentsCustomerProfileConfigsCreateResponse> => {
    return apiMutator<environmentsCustomerProfileConfigsCreateResponse>(
        getEnvironmentsCustomerProfileConfigsCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(customerProfileConfigApi),
        }
    )
}

export type environmentsCustomerProfileConfigsRetrieveResponse200 = {
    data: CustomerProfileConfigApi
    status: 200
}

export type environmentsCustomerProfileConfigsRetrieveResponseSuccess =
    environmentsCustomerProfileConfigsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsCustomerProfileConfigsRetrieveResponse =
    environmentsCustomerProfileConfigsRetrieveResponseSuccess

export const getEnvironmentsCustomerProfileConfigsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/customer_profile_configs/${id}/`
}

export const environmentsCustomerProfileConfigsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsCustomerProfileConfigsRetrieveResponse> => {
    return apiMutator<environmentsCustomerProfileConfigsRetrieveResponse>(
        getEnvironmentsCustomerProfileConfigsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsCustomerProfileConfigsUpdateResponse200 = {
    data: CustomerProfileConfigApi
    status: 200
}

export type environmentsCustomerProfileConfigsUpdateResponseSuccess =
    environmentsCustomerProfileConfigsUpdateResponse200 & {
        headers: Headers
    }
export type environmentsCustomerProfileConfigsUpdateResponse = environmentsCustomerProfileConfigsUpdateResponseSuccess

export const getEnvironmentsCustomerProfileConfigsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/customer_profile_configs/${id}/`
}

export const environmentsCustomerProfileConfigsUpdate = async (
    projectId: string,
    id: string,
    customerProfileConfigApi: NonReadonly<CustomerProfileConfigApi>,
    options?: RequestInit
): Promise<environmentsCustomerProfileConfigsUpdateResponse> => {
    return apiMutator<environmentsCustomerProfileConfigsUpdateResponse>(
        getEnvironmentsCustomerProfileConfigsUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(customerProfileConfigApi),
        }
    )
}

export type environmentsCustomerProfileConfigsPartialUpdateResponse200 = {
    data: CustomerProfileConfigApi
    status: 200
}

export type environmentsCustomerProfileConfigsPartialUpdateResponseSuccess =
    environmentsCustomerProfileConfigsPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsCustomerProfileConfigsPartialUpdateResponse =
    environmentsCustomerProfileConfigsPartialUpdateResponseSuccess

export const getEnvironmentsCustomerProfileConfigsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/customer_profile_configs/${id}/`
}

export const environmentsCustomerProfileConfigsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCustomerProfileConfigApi: NonReadonly<PatchedCustomerProfileConfigApi>,
    options?: RequestInit
): Promise<environmentsCustomerProfileConfigsPartialUpdateResponse> => {
    return apiMutator<environmentsCustomerProfileConfigsPartialUpdateResponse>(
        getEnvironmentsCustomerProfileConfigsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedCustomerProfileConfigApi),
        }
    )
}

export type environmentsCustomerProfileConfigsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsCustomerProfileConfigsDestroyResponseSuccess =
    environmentsCustomerProfileConfigsDestroyResponse204 & {
        headers: Headers
    }
export type environmentsCustomerProfileConfigsDestroyResponse = environmentsCustomerProfileConfigsDestroyResponseSuccess

export const getEnvironmentsCustomerProfileConfigsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/customer_profile_configs/${id}/`
}

export const environmentsCustomerProfileConfigsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsCustomerProfileConfigsDestroyResponse> => {
    return apiMutator<environmentsCustomerProfileConfigsDestroyResponse>(
        getEnvironmentsCustomerProfileConfigsDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}
