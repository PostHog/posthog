/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface CrossProjectDashboardCreatorApi {
    /** Id of the user who created the dashboard. */
    readonly id: number
    /** First name of the user who created the dashboard. */
    readonly first_name: string
    /** Email of the user who created the dashboard. */
    readonly email: string
}

/**
 * A dashboard in the list. It counts its tiles instead of carrying them; read one dashboard for its tiles.
 */
export interface CrossProjectDashboardListItemApi {
    /** Id of the dashboard. */
    readonly id: string
    /** Name shown in the dashboard list and page header. */
    readonly name: string
    /** Optional longer description. */
    readonly description: string
    /** Dashboard-level filters applied to every tile. Supports a date range, an interval, and property filters that refer to a property by name. Filters carrying a project-specific id are rejected. */
    readonly filters: unknown
    /** Tiles from the projects the reader can open. */
    readonly tile_count: number
    /** Distinct projects among the tiles the reader can open. */
    readonly project_count: number
    /** The user who created the dashboard. */
    readonly created_by: CrossProjectDashboardCreatorApi | null
    /** When the dashboard was created. */
    readonly created_at: string
    /**
     * When the dashboard last changed.
     * @nullable
     */
    readonly updated_at: string | null
}

export interface PaginatedCrossProjectDashboardListItemListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CrossProjectDashboardListItemApi[]
}

export interface CrossProjectDashboardTileApi {
    /** Id of the tile. */
    readonly id: string
    /** Id of the project the tile's insight belongs to. */
    project_id: number
    /** Id of the insight the tile renders. */
    insight_id: number
    /** Grid position and size of the tile, keyed by layout size. */
    layouts?: unknown
    /**
     * Optional color applied to the tile.
     * @maxLength 400
     * @nullable
     */
    color?: string | null
    /** Filters applied to this tile only, overriding the dashboard's. Supports a date range and an interval. Filters carrying a project-specific id are rejected. */
    filters_overrides?: unknown
}

/**
 * Carries tile references only.
 *
 * The response holds no insight names, queries or results. Each reader fetches each tile from
 * that tile's own project endpoint, so their access, quota and cache key stay correct there.
 */
export interface CrossProjectDashboardApi {
    /** Id of the dashboard. */
    readonly id: string
    /**
     * Name shown in the dashboard list and page header.
     * @maxLength 400
     */
    name: string
    /**
     * Optional longer description.
     * @maxLength 4000
     */
    description?: string
    /** Dashboard-level filters applied to every tile. Supports a date range, an interval, and property filters that refer to a property by name. Filters carrying a project-specific id are rejected. */
    filters?: unknown
    /** Tiles from the projects the reader can open. */
    readonly tiles: readonly CrossProjectDashboardTileApi[]
    /** The user who created the dashboard. */
    readonly created_by: CrossProjectDashboardCreatorApi | null
    /** When the dashboard was created. */
    readonly created_at: string
    /**
     * When the dashboard last changed.
     * @nullable
     */
    readonly updated_at: string | null
}

export interface PaginatedCrossProjectDashboardTileListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CrossProjectDashboardTileApi[]
}

/**
 * A tile's project and insight never change, so an update carries only its placement and styling.
 */
export interface PatchedCrossProjectDashboardTileUpdateApi {
    /** Grid position and size of the tile, keyed by layout size. */
    layouts?: unknown
    /**
     * Optional color applied to the tile.
     * @maxLength 400
     * @nullable
     */
    color?: string | null
    /** Filters applied to this tile only, overriding the dashboard's. Supports a date range and an interval. Filters carrying a project-specific id are rejected. */
    filters_overrides?: unknown
}

/**
 * Carries tile references only.
 *
 * The response holds no insight names, queries or results. Each reader fetches each tile from
 * that tile's own project endpoint, so their access, quota and cache key stay correct there.
 */
export interface PatchedCrossProjectDashboardApi {
    /** Id of the dashboard. */
    readonly id?: string
    /**
     * Name shown in the dashboard list and page header.
     * @maxLength 400
     */
    name?: string
    /**
     * Optional longer description.
     * @maxLength 4000
     */
    description?: string
    /** Dashboard-level filters applied to every tile. Supports a date range, an interval, and property filters that refer to a property by name. Filters carrying a project-specific id are rejected. */
    filters?: unknown
    /** Tiles from the projects the reader can open. */
    readonly tiles?: readonly CrossProjectDashboardTileApi[]
    /** The user who created the dashboard. */
    readonly created_by?: CrossProjectDashboardCreatorApi | null
    /** When the dashboard was created. */
    readonly created_at?: string
    /**
     * When the dashboard last changed.
     * @nullable
     */
    readonly updated_at?: string | null
}

export type CrossProjectDashboardsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CrossProjectDashboardsTilesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
