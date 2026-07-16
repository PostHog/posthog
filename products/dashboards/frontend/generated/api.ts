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
    AddDashboardWidgetsBatchRequestOpenApiApi,
    AddDashboardWidgetsBatchResponseApi,
    BulkUpdateTagsRequestApi,
    BulkUpdateTagsResponseApi,
    CopyDashboardTemplateApi,
    CopyDashboardTileRequestApi,
    CreateTextTileRequestApi,
    DashboardApi,
    DashboardCollaboratorApi,
    DashboardTemplateApi,
    DashboardTemplatesListParams,
    DashboardTileApi,
    DashboardsBulkUpdateTagsCreateParams,
    DashboardsCopyTileCreateParams,
    DashboardsCreateFromTemplateJsonCreateParams,
    DashboardsCreateParams,
    DashboardsCreateTextTileCreateParams,
    DashboardsCreateUnlistedDashboardCreateParams,
    DashboardsDeleteTileParams,
    DashboardsDestroyParams,
    DashboardsListParams,
    DashboardsMoveTileCreateParams,
    DashboardsMoveTilePartialUpdateParams,
    DashboardsPartialUpdateParams,
    DashboardsReorderTilesCreateParams,
    DashboardsRetrieveParams,
    DashboardsRunInsightsRetrieveParams,
    DashboardsRunWidgetsRetrieveParams,
    DashboardsStreamTilesRetrieveParams,
    DashboardsUpdateParams,
    DashboardsUpdateTextTileCreateParams,
    DashboardsUpdateWidgetsBatchParams,
    DashboardsWidgetCatalogRetrieveParams,
    DashboardsWidgetsBatchCreateParams,
    DataColorThemeApi,
    DataColorThemesListParams,
    DeleteTileRequestApi,
    MoveTileRequestApi,
    PaginatedDashboardBasicListApi,
    PaginatedDashboardTemplateListApi,
    PaginatedDataColorThemeListApi,
    PatchedDashboardTemplateApi,
    PatchedDataColorThemeApi,
    PatchedMoveTileRequestApi,
    PatchedPatchedDashboardOpenApiApi,
    PatchedUpdateDashboardWidgetsBatchRequestOpenApiApi,
    ReorderTilesRequestApi,
    RunInsightsResponseApi,
    RunWidgetsResponseApi,
    UpdateDashboardWidgetsBatchResponseApi,
    UpdateTextTileRequestApi,
    WidgetCatalogResponseApi,
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

export const getDashboardTemplatesListUrl = (projectId: string, params?: DashboardTemplatesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboard_templates/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboard_templates/`
}

export const dashboardTemplatesList = async (
    projectId: string,
    params?: DashboardTemplatesListParams,
    options?: RequestInit
): Promise<PaginatedDashboardTemplateListApi> => {
    return apiMutator<PaginatedDashboardTemplateListApi>(getDashboardTemplatesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardTemplatesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/dashboard_templates/`
}

export const dashboardTemplatesCreate = async (
    projectId: string,
    dashboardTemplateApi?: NonReadonly<DashboardTemplateApi>,
    options?: RequestInit
): Promise<DashboardTemplateApi> => {
    return apiMutator<DashboardTemplateApi>(getDashboardTemplatesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardTemplateApi),
    })
}

export const getDashboardTemplatesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dashboard_templates/${id}/`
}

export const dashboardTemplatesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DashboardTemplateApi> => {
    return apiMutator<DashboardTemplateApi>(getDashboardTemplatesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardTemplatesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dashboard_templates/${id}/`
}

export const dashboardTemplatesUpdate = async (
    projectId: string,
    id: string,
    dashboardTemplateApi?: NonReadonly<DashboardTemplateApi>,
    options?: RequestInit
): Promise<DashboardTemplateApi> => {
    return apiMutator<DashboardTemplateApi>(getDashboardTemplatesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardTemplateApi),
    })
}

export const getDashboardTemplatesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dashboard_templates/${id}/`
}

export const dashboardTemplatesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDashboardTemplateApi?: NonReadonly<PatchedDashboardTemplateApi>,
    options?: RequestInit
): Promise<DashboardTemplateApi> => {
    return apiMutator<DashboardTemplateApi>(getDashboardTemplatesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDashboardTemplateApi),
    })
}

export const getDashboardTemplatesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dashboard_templates/${id}/`
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const dashboardTemplatesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getDashboardTemplatesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getDashboardTemplatesCopyBetweenProjectsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/dashboard_templates/copy_between_projects/`
}

/**
 * Creates a new team-scoped template in the **target** project (URL) from a **team-scoped** source template in the same organization. Global and feature-flag templates return 400. Cross-organization or inaccessible sources return 404. Source and destination projects must differ (400 if equal). Conflicting `template_name` values on the destination are auto-suffixed with `(copy)`, `(copy 2)`, …
 * @summary Copy a team template to this project
 */
export const dashboardTemplatesCopyBetweenProjectsCreate = async (
    projectId: string,
    copyDashboardTemplateApi: CopyDashboardTemplateApi,
    options?: RequestInit
): Promise<DashboardTemplateApi> => {
    return apiMutator<DashboardTemplateApi>(getDashboardTemplatesCopyBetweenProjectsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(copyDashboardTemplateApi),
    })
}

export const getDashboardTemplatesJsonSchemaRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/dashboard_templates/json_schema/`
}

export const dashboardTemplatesJsonSchemaRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDashboardTemplatesJsonSchemaRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardsListUrl = (projectId: string, params?: DashboardsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/`
}

export const dashboardsList = async (
    projectId: string,
    params?: DashboardsListParams,
    options?: RequestInit
): Promise<PaginatedDashboardBasicListApi> => {
    return apiMutator<PaginatedDashboardBasicListApi>(getDashboardsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardsCreateUrl = (projectId: string, params?: DashboardsCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/`
}

export const dashboardsCreate = async (
    projectId: string,
    dashboardApi?: NonReadonly<DashboardApi>,
    params?: DashboardsCreateParams,
    options?: RequestInit
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

export const getDashboardsCollaboratorsListUrl = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/collaborators/`
}

export const dashboardsCollaboratorsList = async (
    projectId: string,
    dashboardId: number,
    options?: RequestInit
): Promise<DashboardCollaboratorApi[]> => {
    return apiMutator<DashboardCollaboratorApi[]>(getDashboardsCollaboratorsListUrl(projectId, dashboardId), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardsCollaboratorsCreateUrl = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/collaborators/`
}

export const dashboardsCollaboratorsCreate = async (
    projectId: string,
    dashboardId: number,
    dashboardCollaboratorApi: NonReadonly<DashboardCollaboratorApi>,
    options?: RequestInit
): Promise<DashboardCollaboratorApi> => {
    return apiMutator<DashboardCollaboratorApi>(getDashboardsCollaboratorsCreateUrl(projectId, dashboardId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardCollaboratorApi),
    })
}

export const getDashboardsCollaboratorsDestroyUrl = (projectId: string, dashboardId: number, userUuid: string) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/collaborators/${userUuid}/`
}

export const dashboardsCollaboratorsDestroy = async (
    projectId: string,
    dashboardId: number,
    userUuid: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDashboardsCollaboratorsDestroyUrl(projectId, dashboardId, userUuid), {
        ...options,
        method: 'DELETE',
    })
}

export const getDashboardsRetrieveUrl = (projectId: string, id: number, params?: DashboardsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/`
}

export const dashboardsRetrieve = async (
    projectId: string,
    id: number,
    params?: DashboardsRetrieveParams,
    options?: RequestInit
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardsUpdateUrl = (projectId: string, id: number, params?: DashboardsUpdateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/`
}

export const dashboardsUpdate = async (
    projectId: string,
    id: number,
    dashboardApi?: NonReadonly<DashboardApi>,
    params?: DashboardsUpdateParams,
    options?: RequestInit
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

export const getDashboardsPartialUpdateUrl = (
    projectId: string,
    id: number,
    params?: DashboardsPartialUpdateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/`
}

export const dashboardsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedPatchedDashboardOpenApiApi?: PatchedPatchedDashboardOpenApiApi,
    params?: DashboardsPartialUpdateParams,
    options?: RequestInit
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsPartialUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedPatchedDashboardOpenApiApi),
    })
}

export const getDashboardsDestroyUrl = (projectId: string, id: number, params?: DashboardsDestroyParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/`
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const dashboardsDestroy = async (
    projectId: string,
    id: number,
    params?: DashboardsDestroyParams,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getDashboardsDestroyUrl(projectId, id, params), {
        ...options,
        method: 'DELETE',
    })
}

export const getDashboardsCopyTileCreateUrl = (
    projectId: string,
    id: number,
    params?: DashboardsCopyTileCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/copy_tile/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/copy_tile/`
}

/**
 * Copy an existing dashboard tile to another dashboard (insight, text card, or widget tile).
 */
export const dashboardsCopyTileCreate = async (
    projectId: string,
    id: number,
    copyDashboardTileRequestApi: CopyDashboardTileRequestApi,
    params?: DashboardsCopyTileCreateParams,
    options?: RequestInit
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsCopyTileCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(copyDashboardTileRequestApi),
    })
}

export const getDashboardsCreateTextTileCreateUrl = (
    projectId: string,
    id: number,
    params?: DashboardsCreateTextTileCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/create_text_tile/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/create_text_tile/`
}

/**
 * Add a markdown text tile to a dashboard.
 *
 * Text tiles render as markdown blocks on the dashboard — useful as section headings, dividers,
 * or annotations between insight tiles to give the dashboard structure.
 */
export const dashboardsCreateTextTileCreate = async (
    projectId: string,
    id: number,
    createTextTileRequestApi: CreateTextTileRequestApi,
    params?: DashboardsCreateTextTileCreateParams,
    options?: RequestInit
): Promise<DashboardTileApi> => {
    return apiMutator<DashboardTileApi>(getDashboardsCreateTextTileCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createTextTileRequestApi),
    })
}

export const getDashboardsDeleteTileUrl = (projectId: string, id: number, params?: DashboardsDeleteTileParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/delete_tile/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/delete_tile/`
}

/**
 * Soft-delete a single tile from a dashboard.
 *
 * Works for text, insight, and button tiles. The underlying Insight, Text, or ButtonTile
 * object is preserved — only the dashboard tile is hidden. To delete the entire dashboard,
 * use the dashboard delete endpoint instead.
 */
export const dashboardsDeleteTile = async (
    projectId: string,
    id: number,
    deleteTileRequestApi: DeleteTileRequestApi,
    params?: DashboardsDeleteTileParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDashboardsDeleteTileUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(deleteTileRequestApi),
    })
}

export const getDashboardsMoveTileCreateUrl = (
    projectId: string,
    id: number,
    params?: DashboardsMoveTileCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/move_tile/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/move_tile/`
}

export const dashboardsMoveTileCreate = async (
    projectId: string,
    id: number,
    moveTileRequestApi: MoveTileRequestApi,
    params?: DashboardsMoveTileCreateParams,
    options?: RequestInit
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsMoveTileCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(moveTileRequestApi),
    })
}

export const getDashboardsMoveTilePartialUpdateUrl = (
    projectId: string,
    id: number,
    params?: DashboardsMoveTilePartialUpdateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/move_tile/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/move_tile/`
}

export const dashboardsMoveTilePartialUpdate = async (
    projectId: string,
    id: number,
    patchedMoveTileRequestApi?: PatchedMoveTileRequestApi,
    params?: DashboardsMoveTilePartialUpdateParams,
    options?: RequestInit
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsMoveTilePartialUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedMoveTileRequestApi),
    })
}

export const getDashboardsReorderTilesCreateUrl = (
    projectId: string,
    id: number,
    params?: DashboardsReorderTilesCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/reorder_tiles/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/reorder_tiles/`
}

export const dashboardsReorderTilesCreate = async (
    projectId: string,
    id: number,
    reorderTilesRequestApi: ReorderTilesRequestApi,
    params?: DashboardsReorderTilesCreateParams,
    options?: RequestInit
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsReorderTilesCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reorderTilesRequestApi),
    })
}

export const getDashboardsRunInsightsRetrieveUrl = (
    projectId: string,
    id: number,
    params?: DashboardsRunInsightsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/run_insights/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/run_insights/`
}

/**
 * Run all insights on a dashboard and return their results.
 */
export const dashboardsRunInsightsRetrieve = async (
    projectId: string,
    id: number,
    params?: DashboardsRunInsightsRetrieveParams,
    options?: RequestInit
): Promise<RunInsightsResponseApi> => {
    return apiMutator<RunInsightsResponseApi>(getDashboardsRunInsightsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardsRunWidgetsRetrieveUrl = (
    projectId: string,
    id: number,
    params: DashboardsRunWidgetsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/run_widgets/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/run_widgets/`
}

export const dashboardsRunWidgetsRetrieve = async (
    projectId: string,
    id: number,
    params: DashboardsRunWidgetsRetrieveParams,
    options?: RequestInit
): Promise<RunWidgetsResponseApi> => {
    return apiMutator<RunWidgetsResponseApi>(getDashboardsRunWidgetsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardsStreamTilesRetrieveUrl = (
    projectId: string,
    id: number,
    params?: DashboardsStreamTilesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/stream_tiles/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/stream_tiles/`
}

/**
 * Stream dashboard metadata and tiles via Server-Sent Events. Sends metadata first, then tiles as they are rendered.
 */
export const dashboardsStreamTilesRetrieve = async (
    projectId: string,
    id: number,
    params?: DashboardsStreamTilesRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDashboardsStreamTilesRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardsUpdateTextTileCreateUrl = (
    projectId: string,
    id: number,
    params?: DashboardsUpdateTextTileCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/update_text_tile/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/update_text_tile/`
}

/**
 * Update the markdown body, layout, or color of an existing text tile on a dashboard.
 */
export const dashboardsUpdateTextTileCreate = async (
    projectId: string,
    id: number,
    updateTextTileRequestApi: UpdateTextTileRequestApi,
    params?: DashboardsUpdateTextTileCreateParams,
    options?: RequestInit
): Promise<DashboardTileApi> => {
    return apiMutator<DashboardTileApi>(getDashboardsUpdateTextTileCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(updateTextTileRequestApi),
    })
}

export const getDashboardsWidgetsBatchCreateUrl = (
    projectId: string,
    id: number,
    params?: DashboardsWidgetsBatchCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/widgets/batch/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/widgets/batch/`
}

/**
 * Add multiple widget tiles to a dashboard in one atomic request.
 */
export const dashboardsWidgetsBatchCreate = async (
    projectId: string,
    id: number,
    addDashboardWidgetsBatchRequestOpenApiApi: AddDashboardWidgetsBatchRequestOpenApiApi,
    params?: DashboardsWidgetsBatchCreateParams,
    options?: RequestInit
): Promise<AddDashboardWidgetsBatchResponseApi> => {
    return apiMutator<AddDashboardWidgetsBatchResponseApi>(getDashboardsWidgetsBatchCreateUrl(projectId, id, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(addDashboardWidgetsBatchRequestOpenApiApi),
    })
}

export const getDashboardsUpdateWidgetsBatchUrl = (
    projectId: string,
    id: number,
    params?: DashboardsUpdateWidgetsBatchParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/widgets/batch_update/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/widgets/batch_update/`
}

/**
 * Update the settings of existing widgets in place, atomically — config, name, and description.
 *
 * Each entry targets a widget by its tile_id and reuses the same write path as the dashboard PATCH endpoint.
 * The widget_type is immutable. This edits widget settings only (config, name, description); tile placement
 * (layouts, show_description) is a dashboard concern — use the dashboard PATCH endpoint or reorder_tiles for
 * that. All updates succeed or fail together. To add new widgets, use the widgets/batch POST endpoint; to
 * remove one, use delete_tile.
 */
export const dashboardsUpdateWidgetsBatch = async (
    projectId: string,
    id: number,
    patchedUpdateDashboardWidgetsBatchRequestOpenApiApi?: PatchedUpdateDashboardWidgetsBatchRequestOpenApiApi,
    params?: DashboardsUpdateWidgetsBatchParams,
    options?: RequestInit
): Promise<UpdateDashboardWidgetsBatchResponseApi> => {
    return apiMutator<UpdateDashboardWidgetsBatchResponseApi>(
        getDashboardsUpdateWidgetsBatchUrl(projectId, id, params),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedUpdateDashboardWidgetsBatchRequestOpenApiApi),
        }
    )
}

export const getDashboardsBulkUpdateTagsCreateUrl = (
    projectId: string,
    params?: DashboardsBulkUpdateTagsCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/bulk_update_tags/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/bulk_update_tags/`
}

/**
 * Bulk update tags on multiple objects.
 *
 * PAT access: this action has no ``required_scopes=`` on the decorator —
 * inheriting viewsets must add ``"bulk_update_tags"`` to their
 * ``scope_object_write_actions`` list to accept personal API keys.
 * Without that opt-in, ``APIScopePermission`` rejects PAT requests with
 * "This action does not support personal API key access". Done per-viewset
 * so granting ``<scope>:write`` for one resource doesn't leak access to
 * sibling resources that share this mixin.
 *
 * Accepts:
 * - {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}
 *
 * Actions:
 * - "add": Add tags to existing tags on each object
 * - "remove": Remove specific tags from each object
 * - "set": Replace all tags on each object with the provided list
 */
export const dashboardsBulkUpdateTagsCreate = async (
    projectId: string,
    bulkUpdateTagsRequestApi: BulkUpdateTagsRequestApi,
    params?: DashboardsBulkUpdateTagsCreateParams,
    options?: RequestInit
): Promise<BulkUpdateTagsResponseApi> => {
    return apiMutator<BulkUpdateTagsResponseApi>(getDashboardsBulkUpdateTagsCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(bulkUpdateTagsRequestApi),
    })
}

export const getDashboardsCreateFromTemplateJsonCreateUrl = (
    projectId: string,
    params?: DashboardsCreateFromTemplateJsonCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/create_from_template_json/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/create_from_template_json/`
}

export const dashboardsCreateFromTemplateJsonCreate = async (
    projectId: string,
    dashboardApi?: NonReadonly<DashboardApi>,
    params?: DashboardsCreateFromTemplateJsonCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDashboardsCreateFromTemplateJsonCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

export const getDashboardsCreateUnlistedDashboardCreateUrl = (
    projectId: string,
    params?: DashboardsCreateUnlistedDashboardCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/create_unlisted_dashboard/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/create_unlisted_dashboard/`
}

/**
 * Creates an unlisted dashboard from template by tag.
 * Enforces uniqueness (one per tag per team).
 * Returns 409 if unlisted dashboard with this tag already exists.
 */
export const dashboardsCreateUnlistedDashboardCreate = async (
    projectId: string,
    dashboardApi?: NonReadonly<DashboardApi>,
    params?: DashboardsCreateUnlistedDashboardCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDashboardsCreateUnlistedDashboardCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

export const getDashboardsWidgetCatalogRetrieveUrl = (
    projectId: string,
    params?: DashboardsWidgetCatalogRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/widget_catalog/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/widget_catalog/`
}

/**
 * List registered dashboard widget types and per-type config_schema documentation for agents.
 */
export const dashboardsWidgetCatalogRetrieve = async (
    projectId: string,
    params?: DashboardsWidgetCatalogRetrieveParams,
    options?: RequestInit
): Promise<WidgetCatalogResponseApi> => {
    return apiMutator<WidgetCatalogResponseApi>(getDashboardsWidgetCatalogRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataColorThemesListUrl = (projectId: string, params?: DataColorThemesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_color_themes/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_color_themes/`
}

export const dataColorThemesList = async (
    projectId: string,
    params?: DataColorThemesListParams,
    options?: RequestInit
): Promise<PaginatedDataColorThemeListApi> => {
    return apiMutator<PaginatedDataColorThemeListApi>(getDataColorThemesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataColorThemesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_color_themes/`
}

export const dataColorThemesCreate = async (
    projectId: string,
    dataColorThemeApi: NonReadonly<DataColorThemeApi>,
    options?: RequestInit
): Promise<DataColorThemeApi> => {
    return apiMutator<DataColorThemeApi>(getDataColorThemesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataColorThemeApi),
    })
}

export const getDataColorThemesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<DataColorThemeApi> => {
    return apiMutator<DataColorThemeApi>(getDataColorThemesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDataColorThemesUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesUpdate = async (
    projectId: string,
    id: number,
    dataColorThemeApi: NonReadonly<DataColorThemeApi>,
    options?: RequestInit
): Promise<DataColorThemeApi> => {
    return apiMutator<DataColorThemeApi>(getDataColorThemesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataColorThemeApi),
    })
}

export const getDataColorThemesPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesPartialUpdate = async (
    projectId: string,
    id: number,
    patchedDataColorThemeApi?: NonReadonly<PatchedDataColorThemeApi>,
    options?: RequestInit
): Promise<DataColorThemeApi> => {
    return apiMutator<DataColorThemeApi>(getDataColorThemesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataColorThemeApi),
    })
}

export const getDataColorThemesDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataColorThemesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
