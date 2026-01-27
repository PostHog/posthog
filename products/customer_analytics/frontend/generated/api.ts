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
