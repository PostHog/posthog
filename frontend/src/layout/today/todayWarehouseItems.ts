import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { isFileSystemImportShown } from 'lib/utils/fileSystemImportFlags'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

export type WarehouseItemKey =
    | 'home'
    | 'sources'
    | 'sql_editor'
    | 'models'
    | 'managed_viewsets'
    | 'data_catalog'
    | 'data_ops'
    | 'usage'
    | 'queries'
    | 'storage'
    | 'access'
    | 'connect'
    | 'settings'

export interface WarehouseItem {
    // pinned: sent as the `item` and `from` properties of `warehouse menu item clicked`, and part of each menu row's data-attr.
    key: WarehouseItemKey
    label: string
    href: string
    iconType: FileSystemIconType
    sceneKey: string
    group: 'home' | 'import' | 'model' | 'manage'
    flag?: FeatureFlagKey
    // Any of these flags also shows the item, as `alternativeFlags` does in a product manifest.
    alternativeFlags?: FeatureFlagKey[]
    // Every one of these flags hides the item, as `hiddenWhenFlags` does in a product manifest.
    hiddenWhenFlags?: FeatureFlagKey[]
    // Pages reached from this item that live under another prefix.
    // They keep the warehouse pane and mark this item as the current page.
    extraPaths?: string[]
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
        key: 'sources',
        label: 'Sources',
        href: urls.sources(),
        iconType: 'data_source',
        sceneKey: 'Sources',
        group: 'import',
    },
    {
        key: 'sql_editor',
        label: 'SQL editor',
        href: urls.sqlEditor(),
        iconType: 'sql_editor',
        sceneKey: 'SQLEditor',
        group: 'model',
    },
    {
        key: 'models',
        label: 'Models',
        href: urls.models(),
        iconType: 'data_modeling',
        sceneKey: 'Models',
        group: 'model',
    },
    {
        key: 'managed_viewsets',
        label: 'Managed viewsets',
        href: urls.dataWarehouseManagedViewsets(),
        iconType: 'managed_viewsets',
        sceneKey: 'DataManagement',
        group: 'model',
        flag: FEATURE_FLAGS.MANAGED_VIEWSETS,
    },
    {
        key: 'data_catalog',
        label: 'Data catalog',
        href: urls.dataCatalog(),
        iconType: 'data_catalog',
        sceneKey: 'DataCatalog',
        group: 'model',
    },
    {
        key: 'data_ops',
        label: 'Data ops',
        href: urls.dataOps(),
        iconType: 'data_warehouse',
        sceneKey: 'DataOps',
        group: 'manage',
        flag: FEATURE_FLAGS.DATA_WAREHOUSE_SCENE,
        alternativeFlags: [FEATURE_FLAGS.MANAGED_TRINO_QUERY],
        // The console takes over its tabs: Settings, Queries and Storage.
        hiddenWhenFlags: [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE],
    },
    {
        key: 'usage',
        label: 'Usage',
        href: urls.warehouseUsage(),
        iconType: 'metrics',
        sceneKey: 'WarehouseUsage',
        group: 'manage',
        flag: FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE,
    },
    {
        key: 'queries',
        label: 'Queries',
        href: urls.warehouseQueries(),
        iconType: 'sql_editor',
        sceneKey: 'WarehouseQueries',
        group: 'manage',
        flag: FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE,
    },
    {
        key: 'storage',
        label: 'Storage',
        href: urls.warehouseStorage(),
        iconType: 'data_warehouse',
        sceneKey: 'WarehouseStorage',
        group: 'manage',
        flag: FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE,
    },
    {
        key: 'access',
        label: 'Access',
        href: urls.warehouseAccess(),
        iconType: 'settings',
        sceneKey: 'WarehouseAccess',
        group: 'manage',
        flag: FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE,
    },
    {
        key: 'connect',
        label: 'Connect',
        href: urls.warehouseConnect(),
        iconType: 'data_pipeline',
        sceneKey: 'WarehouseConnect',
        group: 'manage',
        flag: FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE,
    },
    {
        key: 'settings',
        label: 'Settings',
        href: urls.warehouseSettings(),
        iconType: 'settings',
        sceneKey: 'WarehouseSettings',
        group: 'manage',
        flag: FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE,
    },
]

// Warehouse pages that no menu item names: the new-source wizard and the source connect flow.
// The destination and migration connect pages share the `/data-warehouse` prefix but are not warehouse pages.
const EXTRA_WAREHOUSE_PATHS = ['/data-warehouse/new-source', '/data-warehouse/connect']

export function hrefPath(href: string): string {
    return href.split(/[?#]/)[0]
}

function isUnder(path: string, root: string): boolean {
    return path === root || path.startsWith(`${root}/`)
}

function itemPaths(item: WarehouseItem): string[] {
    return [hrefPath(item.href), ...(item.extraPaths ?? []).map(hrefPath)]
}

const WAREHOUSE_ROUTE_ROOTS = [...new Set([...WAREHOUSE_ITEMS.flatMap(itemPaths), ...EXTRA_WAREHOUSE_PATHS])]

export function isWarehousePath(path: string): boolean {
    return WAREHOUSE_ROUTE_ROOTS.some((root) => isUnder(path, root))
}

const WAREHOUSE_TOOL_PATHS = new Set(WAREHOUSE_ITEMS.filter((item) => item.key !== 'home').flatMap(itemPaths))

export function isWarehouseToolHref(href: string): boolean {
    return WAREHOUSE_TOOL_PATHS.has(hrefPath(href))
}

export function visibleWarehouseItems(featureFlags: FeatureFlagsSet): WarehouseItem[] {
    return WAREHOUSE_ITEMS.filter(
        (item) =>
            isFileSystemImportShown(item, featureFlags) &&
            !getProductAccessDisabledReason({ sceneKey: item.sceneKey, path: item.label })
    )
}

/** The menu item for the page at `path`: the one with the longest matching path. */
export function warehouseItemForLocation(path: string, items: WarehouseItem[]): WarehouseItem | null {
    let match: WarehouseItem | null = null
    let matchLength = -1
    for (const item of items) {
        for (const itemPath of itemPaths(item)) {
            if (isUnder(path, itemPath) && itemPath.length > matchLength) {
                match = item
                matchLength = itemPath.length
            }
        }
    }
    return match
}
