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
    CanvasApi,
    CanvasBuildActionApi,
    CanvasBuildApi,
    CanvasBuildsResponseApi,
    CanvasCreateApi,
    CanvasRevertApi,
    CanvasSourceEditApi,
    CanvasSourcePublishApi,
    CanvasSourcePublishResponseApi,
    CanvasSourceResponseApi,
    CanvasValidateRequestApi,
    CanvasValidateResponseApi,
    CanvasesBuildsRetrieveParams,
    CanvasesListParams,
    CanvasesSourceRetrieveParams,
    CanvasesVersionsRetrieveParams,
    PaginatedCanvasListApi,
    PaginatedCanvasVersionListApi,
    PatchedCanvasUpdateApi,
} from './api.schemas'

export const getCanvasesListUrl = (projectId: string, params?: CanvasesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/canvases/?${stringifiedParams}`
        : `/api/projects/${projectId}/canvases/`
}

/**
 * Canvases: agent-built sandboxed browser apps, filed into channels.
 *
 * Source is versioned per publish and built server-side; the canvas app
 * renders the published build's artifact from the isolated artifact origin.
 */
export const canvasesList = async (
    projectId: string,
    params?: CanvasesListParams,
    options?: RequestInit
): Promise<PaginatedCanvasListApi> => {
    return apiMutator<PaginatedCanvasListApi>(getCanvasesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCanvasesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/canvases/`
}

/**
 * Create a new, empty canvas in a channel; give it source by publishing a project.
 */
export const canvasesCreate = async (
    projectId: string,
    canvasCreateApi: CanvasCreateApi,
    options?: RequestInit
): Promise<CanvasApi> => {
    return apiMutator<CanvasApi>(getCanvasesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasCreateApi),
    })
}

export const getCanvasesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/`
}

/**
 * Canvases: agent-built sandboxed browser apps, filed into channels.
 *
 * Source is versioned per publish and built server-side; the canvas app
 * renders the published build's artifact from the isolated artifact origin.
 */
export const canvasesRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<CanvasApi> => {
    return apiMutator<CanvasApi>(getCanvasesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCanvasesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/`
}

/**
 * Update canvas metadata (name, author context, pin, generation-task pointer).
 */
export const canvasesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCanvasUpdateApi?: PatchedCanvasUpdateApi,
    options?: RequestInit
): Promise<CanvasApi> => {
    return apiMutator<CanvasApi>(getCanvasesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCanvasUpdateApi),
    })
}

export const getCanvasesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/`
}

/**
 * Canvases: agent-built sandboxed browser apps, filed into channels.
 *
 * Source is versioned per publish and built server-side; the canvas app
 * renders the published build's artifact from the isolated artifact origin.
 */
export const canvasesDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getCanvasesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getCanvasesBuildsRetrieveUrl = (projectId: string, id: string, params?: CanvasesBuildsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/canvases/${id}/builds/?${stringifiedParams}`
        : `/api/projects/${projectId}/canvases/${id}/builds/`
}

/**
 * Read the canvas's build lifecycle: live pointers plus recent builds.
 *
 * A publish queues a build; poll this until it is ready (the live pointer
 * advances) or failed (fix the error diagnostics and publish again — the
 * last good build stays live).
 */
export const canvasesBuildsRetrieve = async (
    projectId: string,
    id: string,
    params?: CanvasesBuildsRetrieveParams,
    options?: RequestInit
): Promise<CanvasBuildsResponseApi> => {
    return apiMutator<CanvasBuildsResponseApi>(getCanvasesBuildsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getCanvasesBuildActionCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/builds/action/`
}

/**
 * Apply a lifecycle action (retry, pin, unpin, cancel) to one build.
 */
export const canvasesBuildActionCreate = async (
    projectId: string,
    id: string,
    canvasBuildActionApi: CanvasBuildActionApi,
    options?: RequestInit
): Promise<CanvasBuildApi> => {
    return apiMutator<CanvasBuildApi>(getCanvasesBuildActionCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasBuildActionApi),
    })
}

export const getCanvasesEditCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/edit/`
}

/**
 * Publish per-file edits against the canvas's current source project.
 *
 * Diff-aware alternative to sending the complete project: each operation
 * sets a file's content or (content null) deletes it, applied to the head
 * the caller read. `expected_current_version_id` is mandatory here —
 * relative edits against an unverified base could silently merge into
 * someone else's newer work.
 */
export const canvasesEditCreate = async (
    projectId: string,
    id: string,
    canvasSourceEditApi: CanvasSourceEditApi,
    options?: RequestInit
): Promise<CanvasSourcePublishResponseApi> => {
    return apiMutator<CanvasSourcePublishResponseApi>(getCanvasesEditCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasSourceEditApi),
    })
}

export const getCanvasesPublishCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/publish/`
}

/**
 * Publish a complete source project as the canvas's new head version.
 *
 * Validation errors reject the publish (400) and leave the canvas
 * untouched; a stale `expected_current_version_id` is rejected with 409.
 * A successful publish queues a server-side build.
 */
export const canvasesPublishCreate = async (
    projectId: string,
    id: string,
    canvasSourcePublishApi: CanvasSourcePublishApi,
    options?: RequestInit
): Promise<CanvasSourcePublishResponseApi> => {
    return apiMutator<CanvasSourcePublishResponseApi>(getCanvasesPublishCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasSourcePublishApi),
    })
}

export const getCanvasesRevertCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/revert/`
}

/**
 * Move the canvas's head back to an existing source version and rebuild it.
 */
export const canvasesRevertCreate = async (
    projectId: string,
    id: string,
    canvasRevertApi: CanvasRevertApi,
    options?: RequestInit
): Promise<CanvasBuildApi> => {
    return apiMutator<CanvasBuildApi>(getCanvasesRevertCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasRevertApi),
    })
}

export const getCanvasesSourceRetrieveUrl = (projectId: string, id: string, params?: CanvasesSourceRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/canvases/${id}/source/?${stringifiedParams}`
        : `/api/projects/${projectId}/canvases/${id}/source/`
}

/**
 * Read the canvas's source project and its `current_version_id`.
 *
 * Always call this before editing: edit the returned files, then publish
 * the complete project passing the returned version id as
 * `expected_current_version_id` so concurrent edits are not overwritten.
 * `?version_id=` reads a historical version instead of the head.
 */
export const canvasesSourceRetrieve = async (
    projectId: string,
    id: string,
    params?: CanvasesSourceRetrieveParams,
    options?: RequestInit
): Promise<CanvasSourceResponseApi> => {
    return apiMutator<CanvasSourceResponseApi>(getCanvasesSourceRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getCanvasesValidateCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/validate/`
}

/**
 * Validate a candidate source project without publishing it. Side-effect free.
 */
export const canvasesValidateCreate = async (
    projectId: string,
    id: string,
    canvasValidateRequestApi: CanvasValidateRequestApi,
    options?: RequestInit
): Promise<CanvasValidateResponseApi> => {
    return apiMutator<CanvasValidateResponseApi>(getCanvasesValidateCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasValidateRequestApi),
    })
}

export const getCanvasesVersionsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: CanvasesVersionsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/canvases/${id}/versions/?${stringifiedParams}`
        : `/api/projects/${projectId}/canvases/${id}/versions/`
}

/**
 * The canvas's source-version history, newest first (metadata only).
 */
export const canvasesVersionsRetrieve = async (
    projectId: string,
    id: string,
    params?: CanvasesVersionsRetrieveParams,
    options?: RequestInit
): Promise<PaginatedCanvasVersionListApi> => {
    return apiMutator<PaginatedCanvasVersionListApi>(getCanvasesVersionsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}
