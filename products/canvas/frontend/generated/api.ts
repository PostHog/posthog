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
    CanvasActionInvokeApi,
    CanvasActionResultApi,
    CanvasActionsResponseApi,
    CanvasAgentRequestApi,
    CanvasAgentRequestResultApi,
    CanvasApi,
    CanvasBuildActionApi,
    CanvasBuildApi,
    CanvasBuildsResponseApi,
    CanvasCreateApi,
    CanvasErrorReportResultApi,
    CanvasFixRequestResultApi,
    CanvasLayoutPatchApi,
    CanvasLayoutPublishApi,
    CanvasLayoutPublishResponseApi,
    CanvasLayoutResponseApi,
    CanvasPromoteApi,
    CanvasPublishCurrentVersionApi,
    CanvasReportErrorApi,
    CanvasRequestFixApi,
    CanvasRevertApi,
    CanvasSourceDraftApi,
    CanvasSourceDraftResponseApi,
    CanvasSourceEditApi,
    CanvasSourcePublishApi,
    CanvasSourcePublishResponseApi,
    CanvasSourceResponseApi,
    CanvasStateEntryApi,
    CanvasStateResponseApi,
    CanvasStateSetApi,
    CanvasValidateRequestApi,
    CanvasValidateResponseApi,
    CanvasesBuildsRetrieveParams,
    CanvasesDraftsRetrieveParams,
    CanvasesLayoutRetrieveParams,
    CanvasesListParams,
    CanvasesSourceRetrieveParams,
    CanvasesStateRetrieveParams,
    CanvasesVersionsRetrieveParams,
    PaginatedCanvasDraftListApi,
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
 * Update canvas metadata, including the space it belongs to.
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

export const getCanvasesActionsInvokeUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/actions/invoke/`
}

/**
 * Invoke one registered action verb as the viewer.
 *
 * The canvas must declare the verb in capabilities.posthog.actions (the
 * reviewed permission boundary); the write itself runs with the viewer's
 * own permissions, exactly as if they acted in the app.
 */
export const canvasesActionsInvoke = async (
    projectId: string,
    id: string,
    canvasActionInvokeApi: CanvasActionInvokeApi,
    options?: RequestInit
): Promise<CanvasActionResultApi> => {
    return apiMutator<CanvasActionResultApi>(getCanvasesActionsInvokeUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasActionInvokeApi),
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

export const getCanvasesDraftCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/draft/`
}

/**
 * Stage a complete source project as a draft version and build it, without publishing.
 *
 * The draft gets the same validation, versioning, and server-side build as
 * a publish, but the canvas's head and live build never move, so nothing
 * changes for viewers. Promote the version with `promote` to make it live.
 * The response reports how the draft's declared capabilities widen the
 * current head's, so growth in access can be reviewed before it ships.
 * No version guard applies: a draft conflicts with nothing.
 */
export const canvasesDraftCreate = async (
    projectId: string,
    id: string,
    canvasSourceDraftApi: CanvasSourceDraftApi,
    options?: RequestInit
): Promise<CanvasSourceDraftResponseApi> => {
    return apiMutator<CanvasSourceDraftResponseApi>(getCanvasesDraftCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasSourceDraftApi),
    })
}

export const getCanvasesDraftsRetrieveUrl = (projectId: string, id: string, params?: CanvasesDraftsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/canvases/${id}/drafts/?${stringifiedParams}`
        : `/api/projects/${projectId}/canvases/${id}/drafts/`
}

/**
 * The canvas's staged draft versions, newest first, each with its latest build status.
 *
 * A draft is a version that was built but never made the head. Preview one
 * with `source?version_id=`, then make it live with `promote`.
 */
export const canvasesDraftsRetrieve = async (
    projectId: string,
    id: string,
    params?: CanvasesDraftsRetrieveParams,
    options?: RequestInit
): Promise<PaginatedCanvasDraftListApi> => {
    return apiMutator<PaginatedCanvasDraftListApi>(getCanvasesDraftsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
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

export const getCanvasesLayoutRetrieveUrl = (projectId: string, id: string, params?: CanvasesLayoutRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/canvases/${id}/layout/?${stringifiedParams}`
        : `/api/projects/${projectId}/canvases/${id}/layout/`
}

/**
 * Read a grid canvas's layout document and its `current_version_id`.
 *
 * Always call this before editing: pass the returned version id as
 * `expected_current_version_id` on publish/patch so concurrent edits are
 * not overwritten. A grid canvas with no versions yet returns the
 * default empty layout with a null version id.
 */
export const canvasesLayoutRetrieve = async (
    projectId: string,
    id: string,
    params?: CanvasesLayoutRetrieveParams,
    options?: RequestInit
): Promise<CanvasLayoutResponseApi> => {
    return apiMutator<CanvasLayoutResponseApi>(getCanvasesLayoutRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getCanvasesLayoutPatchCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/layout/patch/`
}

/**
 * Apply surgical operations to the grid canvas's current layout.
 *
 * The default write path for both the editor and agents: add, move,
 * resize, fill, or remove one placement without resending the layout.
 * `expected_current_version_id` is mandatory so an agent filling a box
 * and a user rearranging widgets cannot overwrite each other.
 */
export const canvasesLayoutPatchCreate = async (
    projectId: string,
    id: string,
    canvasLayoutPatchApi: CanvasLayoutPatchApi,
    options?: RequestInit
): Promise<CanvasLayoutPublishResponseApi> => {
    return apiMutator<CanvasLayoutPublishResponseApi>(getCanvasesLayoutPatchCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasLayoutPatchApi),
    })
}

export const getCanvasesLayoutPublishCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/layout/publish/`
}

/**
 * Publish a complete layout document as the grid canvas's new head version.
 *
 * Layout is data, not code: the new version is live immediately, with no
 * build. Validation errors reject the publish (400) and leave the canvas
 * untouched; a stale `expected_current_version_id` is rejected with 409.
 */
export const canvasesLayoutPublishCreate = async (
    projectId: string,
    id: string,
    canvasLayoutPublishApi: CanvasLayoutPublishApi,
    options?: RequestInit
): Promise<CanvasLayoutPublishResponseApi> => {
    return apiMutator<CanvasLayoutPublishResponseApi>(getCanvasesLayoutPublishCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasLayoutPublishApi),
    })
}

export const getCanvasesPromoteCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/promote/`
}

/**
 * Make a draft version the canvas's live head.
 *
 * A draft whose build is ready goes live immediately, with no rebuild;
 * otherwise a fresh build is queued. Returns that build.
 */
export const canvasesPromoteCreate = async (
    projectId: string,
    id: string,
    canvasPromoteApi: CanvasPromoteApi,
    options?: RequestInit
): Promise<CanvasBuildApi> => {
    return apiMutator<CanvasBuildApi>(getCanvasesPromoteCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasPromoteApi),
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

export const getCanvasesPublishCurrentVersionCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/publish-current-version/`
}

/**
 * Queue a build for the current source version without changing source or metadata.
 */
export const canvasesPublishCurrentVersionCreate = async (
    projectId: string,
    id: string,
    canvasPublishCurrentVersionApi: CanvasPublishCurrentVersionApi,
    options?: RequestInit
): Promise<CanvasBuildApi> => {
    return apiMutator<CanvasBuildApi>(getCanvasesPublishCurrentVersionCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasPublishCurrentVersionApi),
    })
}

export const getCanvasesReportErrorCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/report_error/`
}

/**
 * Report a runtime error observed while rendering a canvas build.
 *
 * Files the report in the authoring task's thread (deduped per build and
 * error type) so the canvas's agent can be asked to fix it. Reports never
 * start an agent run by themselves — dispatch is `request_fix`. Only the
 * error class crosses the server; full messages and stacks stay
 * client-side because rendering sessions can carry viewer data.
 */
export const canvasesReportErrorCreate = async (
    projectId: string,
    id: string,
    canvasReportErrorApi: CanvasReportErrorApi,
    options?: RequestInit
): Promise<CanvasErrorReportResultApi> => {
    return apiMutator<CanvasErrorReportResultApi>(getCanvasesReportErrorCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasReportErrorApi),
    })
}

export const getCanvasesRequestAgentCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/request_agent/`
}

/**
 * Route a viewer-approved change request to the canvas's authoring task.
 */
export const canvasesRequestAgentCreate = async (
    projectId: string,
    id: string,
    canvasAgentRequestApi: CanvasAgentRequestApi,
    options?: RequestInit
): Promise<CanvasAgentRequestResultApi> => {
    return apiMutator<CanvasAgentRequestResultApi>(getCanvasesRequestAgentCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasAgentRequestApi),
    })
}

export const getCanvasesRequestFixCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/request_fix/`
}

/**
 * Wake the canvas's authoring agent to fix a failing build or runtime error.
 *
 * Starts (or signals) an agent run on the authoring task, instructed to
 * stage the fix as a draft the user reviews and promotes. This is the
 * human-initiated dispatch step behind error reports; it spends agent
 * compute, so it never fires automatically, and only the authoring
 * task's creator may dispatch — the run executes with their credentials.
 */
export const canvasesRequestFixCreate = async (
    projectId: string,
    id: string,
    canvasRequestFixApi: CanvasRequestFixApi,
    options?: RequestInit
): Promise<CanvasFixRequestResultApi> => {
    return apiMutator<CanvasFixRequestResultApi>(getCanvasesRequestFixCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasRequestFixApi),
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

export const getCanvasesStateRetrieveUrl = (projectId: string, id: string, params?: CanvasesStateRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/canvases/${id}/state/?${stringifiedParams}`
        : `/api/projects/${projectId}/canvases/${id}/state/`
}

/**
 * Read the canvas's runtime key-value state (the ph.state store).
 *
 * Returns shared entries plus the authenticated user's own user-scoped
 * entries — never another user's.
 */
export const canvasesStateRetrieve = async (
    projectId: string,
    id: string,
    params?: CanvasesStateRetrieveParams,
    options?: RequestInit
): Promise<CanvasStateResponseApi> => {
    return apiMutator<CanvasStateResponseApi>(getCanvasesStateRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getCanvasesStateSetUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/canvases/${id}/state/set/`
}

/**
 * Write one key of the canvas's runtime state, or delete it with a null value.
 */
export const canvasesStateSet = async (
    projectId: string,
    id: string,
    canvasStateSetApi: CanvasStateSetApi,
    options?: RequestInit
): Promise<CanvasStateEntryApi | void> => {
    return apiMutator<CanvasStateEntryApi | void>(getCanvasesStateSetUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(canvasStateSetApi),
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
 * The canvas's published source-version history, newest first (metadata only).
 *
 * Drafts are excluded: they are staged versions that have never been the
 * head, so they are not part of the undo/revert timeline. Fetch a draft's
 * files with `source?version_id=` to preview it before promoting.
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

export const getCanvasesActionsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/canvases/actions/`
}

/**
 * List the action registry: every verb a canvas may declare and invoke.
 */
export const canvasesActionsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<CanvasActionsResponseApi> => {
    return apiMutator<CanvasActionsResponseApi>(getCanvasesActionsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getCanvasesHomeCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/canvases/home/`
}

/**
 * Get or provision the caller's home canvas.
 *
 * Idempotent: returns the user's existing home canvas, or creates a grid
 * canvas in their personal channel and points their home preference at
 * it. The home surface calls this on open.
 */
export const canvasesHomeCreate = async (projectId: string, options?: RequestInit): Promise<CanvasApi> => {
    return apiMutator<CanvasApi>(getCanvasesHomeCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}
