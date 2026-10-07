import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

export type WarehouseItemKey =
    | 'home'
    | 'sql_editor'
    | 'data_catalog'
    | 'sources'
    | 'business_intelligence'
    | 'models'
    | 'warehouse_destinations'
    | 'sql_variables'
    | 'data_ops'

export interface WarehouseItem {
    // pinned: sent as the `item` and `from` properties of `warehouse menu item clicked`, and part of each menu row's data-attr.
    key: WarehouseItemKey
    label: string
    href: string
    iconType: FileSystemIconType
    sceneKey: string
    group: 'home' | 'primary' | 'secondary'
    flag?: FeatureFlagKey
}

export const WAREHOUSE_ITEMS: WarehouseItem[] = [
    {
        key: 'home',
        label: 'Home',
        href: urls.warehouse(),
        iconType: 'data_warehouse',
        sceneKey: 'WarehouseHome',
        group: 'home',
    },
    {
        key: 'sql_editor',
        label: 'SQL editor',
        href: urls.sqlEditor(),
        iconType: 'sql_editor',
        sceneKey: 'SQLEditor',
        group: 'primary',
    },
    {
        key: 'data_catalog',
        label: 'Data catalog',
        href: urls.dataCatalog(),
        iconType: 'data_catalog',
        sceneKey: 'DataCatalog',
        group: 'primary',
    },
    {
        key: 'sources',
        label: 'Sources',
        href: urls.sources(),
        iconType: 'data_source',
        sceneKey: 'Sources',
        group: 'primary',
    },
    {
        key: 'business_intelligence',
        label: 'Business intelligence',
        href: urls.businessIntelligence(),
        iconType: 'business_intelligence',
        sceneKey: 'BusinessIntelligence',
        group: 'primary',
        flag: FEATURE_FLAGS.SQL_EDITOR_BI_MODE,
    },
    {
        key: 'models',
        label: 'Models',
        href: urls.models(),
        iconType: 'data_modeling',
        sceneKey: 'Models',
        group: 'primary',
    },
    {
        key: 'warehouse_destinations',
        label: 'Warehouse destinations',
        href: urls.warehouseDestinations(),
        iconType: 'warehouse_destination',
        sceneKey: 'WarehouseDestinations',
        group: 'primary',
        flag: FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION,
    },
    {
        key: 'sql_variables',
        label: 'SQL variables',
        href: urls.variables(),
        iconType: 'sql_variable',
        sceneKey: 'DataManagement',
        group: 'secondary',
    },
    {
        key: 'data_ops',
        label: 'Data ops',
        href: urls.dataOps(),
        iconType: 'data_warehouse',
        sceneKey: 'DataOps',
        group: 'secondary',
        flag: FEATURE_FLAGS.DATA_WAREHOUSE_SCENE,
    },
]

// Warehouse pages that no menu item names: the new-source wizard and the connect flow under this prefix.
const EXTRA_WAREHOUSE_PATHS = ['/data-warehouse']

export function hrefPath(href: string): string {
    return href.split(/[?#]/)[0]
}

function isUnder(path: string, root: string): boolean {
    return path === root || path.startsWith(`${root}/`)
}

const WAREHOUSE_ROUTE_ROOTS = [
    ...new Set([...WAREHOUSE_ITEMS.map((item) => hrefPath(item.href)), ...EXTRA_WAREHOUSE_PATHS]),
]

export function isWarehousePath(path: string): boolean {
    return WAREHOUSE_ROUTE_ROOTS.some((root) => isUnder(path, root))
}

const WAREHOUSE_TOOL_PATHS = new Set(
    WAREHOUSE_ITEMS.filter((item) => item.key !== 'home').map((item) => hrefPath(item.href))
)

export function isWarehouseToolHref(href: string): boolean {
    return WAREHOUSE_TOOL_PATHS.has(hrefPath(href))
}

export function visibleWarehouseItems(featureFlags: FeatureFlagsSet): WarehouseItem[] {
    return WAREHOUSE_ITEMS.filter(
        (item) =>
            (!item.flag || !!featureFlags[item.flag as keyof FeatureFlagsSet]) &&
            !getProductAccessDisabledReason({ sceneKey: item.sceneKey, path: item.label })
    )
}

/** The menu item for the page at `path`: the one with the longest matching path. */
export function warehouseItemForLocation(path: string, items: WarehouseItem[]): WarehouseItem | null {
    let match: WarehouseItem | null = null
    for (const item of items) {
        const itemPath = hrefPath(item.href)
        if (!isUnder(path, itemPath)) {
            continue
        }
        if (!match || itemPath.length > hrefPath(match.href).length) {
            match = item
        }
    }
    return match
}
