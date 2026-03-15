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
    AnnotationApi,
    AnnotationsListParams,
    PaginatedAnnotationListApi,
    PatchedAnnotationApi,
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

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const getAnnotationsListUrl = (projectId: string, params?: AnnotationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/annotations/?${stringifiedParams}`
        : `/api/projects/${projectId}/annotations/`
}

export const annotationsList = async (
    projectId: string,
    params?: AnnotationsListParams,
    options?: RequestInit
): Promise<PaginatedAnnotationListApi> => {
    return apiMutator<PaginatedAnnotationListApi>(getAnnotationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const getAnnotationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/annotations/`
}

export const annotationsCreate = async (
    projectId: string,
    annotationApi: NonReadonly<AnnotationApi>,
    options?: RequestInit
): Promise<AnnotationApi> => {
    return apiMutator<AnnotationApi>(getAnnotationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(annotationApi),
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const getAnnotationsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/annotations/${id}/`
}

export const annotationsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<AnnotationApi> => {
    return apiMutator<AnnotationApi>(getAnnotationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const getAnnotationsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/annotations/${id}/`
}

export const annotationsUpdate = async (
    projectId: string,
    id: number,
    annotationApi: NonReadonly<AnnotationApi>,
    options?: RequestInit
): Promise<AnnotationApi> => {
    return apiMutator<AnnotationApi>(getAnnotationsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(annotationApi),
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const getAnnotationsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/annotations/${id}/`
}

export const annotationsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedAnnotationApi: NonReadonly<PatchedAnnotationApi>,
    options?: RequestInit
): Promise<AnnotationApi> => {
    return apiMutator<AnnotationApi>(getAnnotationsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAnnotationApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getAnnotationsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/annotations/${id}/`
}

export const annotationsDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getAnnotationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
