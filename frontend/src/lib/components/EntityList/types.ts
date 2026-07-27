import { ReactNode } from 'react'

import { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { Scene } from 'scenes/sceneTypes'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

/**
 * `client` fetches the full collection once, then searches, sorts and pages in the browser.
 * `server` re-runs `load` whenever the search term, ordering or page changes.
 */
export type EntityListMode = 'client' | 'server'

/**
 * A table column with the data-index parameter left open. `LemonTableColumn` is invariant in that
 * parameter, so pinning it to `keyof T | undefined` would make every list cast the helpers in
 * `columnUtils`, which return a literal key.
 */
export type EntityListColumn<T extends Record<string, any>> = LemonTableColumn<T, any>

/** One page of results, as returned by `EntityListDefinition.load`. */
export interface EntityListPage<T> {
    results: T[]
    /** Total across every page. Server-mode lists must set it, client-mode lists can leave it out. */
    count?: number
}

/** What the framework knows about the current view when it asks a definition for data. */
export interface EntityListQuery {
    search: string
    page: number
    limit: number
    offset: number
    /** DRF-style ordering, for example `-created_at`. */
    orderBy: string | null
}

export interface EntityListRowHelpers {
    /** Re-runs `load` with the current query. Call this after mutating a row. */
    refresh: () => void
}

/**
 * Leading column of every entity list. The framework renders it as a `LemonTableLink` pointing at
 * the entity's detail page, so a definition only has to say what the row is called.
 */
export interface EntityListNameColumn<T> {
    /** Header label. Defaults to `Name`. */
    title?: string
    render: (record: T) => JSX.Element | string
    description?: (record: T) => ReactNode
    /**
     * Detail page for a row. Defaults to the `href` the product manifest registered for `type`,
     * called with the row key, so entities in the file system registry get their links for free.
     */
    to?: (record: T) => string | undefined
    width?: string
    /** Sent as `order_by` in server mode. Defaults to `name`. */
    key?: string
    /** Client mode only. Server-mode ordering goes through `key`. */
    sorter?: (a: T, b: T) => number
}

export interface EntityListNewButton {
    label: string
    /** Pass a function when the target depends on runtime state such as the current search params. */
    to?: string | (() => string)
    onClick?: () => void
    /** Resolved on render, so access-control checks see the current user rather than module load. */
    disabledReason?: () => string | undefined
    'data-attr'?: string
    /** Registers the shared "new" keybind under this name. Leave out to skip the shortcut. */
    shortcutName?: string
    sideAction?: LemonButtonProps['sideAction']
}

export interface EntityListDefinition<T extends Record<string, any>> {
    /**
     * File system type key from the product manifest (`fileSystemTypes`). When it resolves, the
     * framework takes the icon, the singular noun and the detail URL from the manifest rather than
     * asking the product to restate them. Entities that are not in the file system registry pass a
     * free-form key and supply `nouns`, `iconType` and `nameColumn.to` themselves.
     */
    type: string
    scene: Scene
    /** Route the list lives at. Used for the breadcrumb and to sync filters into the URL. */
    url: string
    productKey?: ProductKey
    activityScope?: ActivityScope
    emptyState?: SceneProductEmptyState

    /** These three default to the scene's entry in `sceneConfigurations`. */
    name?: string
    description?: string
    iconType?: FileSystemIconType

    /** Singular and plural. Defaults to the manifest name, lowercased, with an `s` appended. */
    nouns?: [string, string]

    mode: EntityListMode
    /** Client-mode implementations may ignore `limit`, `offset` and `orderBy` and return everything. */
    load: (query: EntityListQuery) => Promise<EntityListPage<T>>
    /** Server mode: rows per request. Client mode: rows per page, or unpaginated when left out. */
    pageSize?: number
    rowKey?: keyof T & string
    /** Ordering applied before the user sorts anything. Server mode only. */
    defaultOrderBy?: string

    search?: {
        placeholder: string
        /** Client mode only: the fields fuzzy-matched against the search term. */
        keys?: (keyof T & string)[]
    }

    nameColumn: EntityListNameColumn<T>
    /** Everything after the name column. The trailing "..." menu is added from `rowMenu`. */
    columns: EntityListColumn<T>[]
    rowMenu?: (record: T, helpers: EntityListRowHelpers) => ReactNode

    newButton?: EntityListNewButton
    /** Rendered next to the new-entity button. */
    extraActions?: ReactNode
    /** Product-specific content between the title and the search bar. */
    banner?: (state: EntityListBannerState) => ReactNode
    /**
     * Drop the table when the product has no entities at all. Only for lists whose first-run state
     * still comes from the deprecated `ProductIntroduction` in `banner`; once a list declares
     * `emptyState`, the app shell replaces the whole scene and this is unnecessary.
     */
    hideTableWhenEmpty?: boolean
}

export interface EntityListBannerState {
    /** No rows, nothing loading, and the user has not searched. */
    isEmpty: boolean
    isNarrowed: boolean
}
