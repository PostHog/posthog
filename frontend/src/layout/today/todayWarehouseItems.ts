import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { isFileSystemImportShown } from 'lib/utils/fileSystemImportFlags'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

export type WarehouseItemKey =
    | 'home'
    | 'sql_editor'
    | 'posthog_data'
    | 'source_data'
    | 'models'
    | 'models_list'
    | 'models_usage'
    | 'models_lineage'
    | 'models_data_quality'
    | 'managed_viewsets'
    | 'data_catalog'
    | 'data_catalog_relationships'
    | 'data_catalog_certifications'
    | 'data_catalog_usage'
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
    // What the menu button shows on this page, when the label alone would not say which page it is.
    title?: string
    href: string
    iconType: FileSystemIconType
    sceneKey: string
    group: 'home' | 'data' | 'models' | 'data_catalog' | 'manage'
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
        key: 'sql_editor',
        label: 'SQL editor',
        href: urls.sqlEditor(),
        iconType: 'sql_editor',
        sceneKey: 'SQLEditor',
        group: 'home',
    },
    {
        key: 'posthog_data',
        label: 'PostHog data',
        href: urls.warehousePostHogData(),
        iconType: 'data_pipeline',
        sceneKey: 'WarehousePostHogData',
        group: 'data',
        flag: FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE,
    },
    {
        key: 'source_data',
        label: 'Source data',
        href: urls.warehouseSourceData(),
        iconType: 'data_source',
        sceneKey: 'WarehouseSourceData',
        group: 'data',
        flag: FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE,
    },
    // The tabs of the Models page, one item each. The first is the page without a `tab` parameter.
    {
        key: 'models',
        label: 'Overview',
        title: 'Models overview',
        href: urls.models(),
        iconType: 'data_modeling',
        sceneKey: 'Models',
        group: 'models',
    },
    {
        key: 'models_list',
        label: 'Models',
        href: urls.models('models'),
        iconType: 'data_modeling',
        sceneKey: 'Models',
        group: 'models',
    },
    {
        key: 'models_usage',
        label: 'Usage',
        title: 'Models usage',
        href: urls.models('usage'),
        iconType: 'metrics',
        sceneKey: 'Models',
        group: 'models',
        flag: FEATURE_FLAGS.DATA_MODELING_USAGE,
    },
    {
        key: 'models_lineage',
        label: 'Lineage',
        href: urls.models('lineage'),
        iconType: 'data_modeling',
        sceneKey: 'Models',
        group: 'models',
    },
    {
        key: 'models_data_quality',
        label: 'Data quality',
        href: urls.models('data-quality'),
        iconType: 'data_modeling',
        sceneKey: 'Models',
        group: 'models',
    },
    {
        key: 'managed_viewsets',
        label: 'Managed viewsets',
        href: urls.dataWarehouseManagedViewsets(),
        iconType: 'managed_viewsets',
        sceneKey: 'DataManagement',
        group: 'models',
        flag: FEATURE_FLAGS.MANAGED_VIEWSETS,
    },
    // The tabs of the Data catalog page, one item each. The first is the page without a `tab` parameter.
    {
        key: 'data_catalog',
        label: 'Metrics',
        href: urls.dataCatalog(),
        iconType: 'data_catalog',
        sceneKey: 'DataCatalog',
        group: 'data_catalog',
    },
    {
        key: 'data_catalog_relationships',
        label: 'Relationships',
        href: urls.dataCatalog('relationships'),
        iconType: 'data_catalog',
        sceneKey: 'DataCatalog',
        group: 'data_catalog',
    },
    {
        key: 'data_catalog_certifications',
        label: 'Certifications',
        href: urls.dataCatalog('certifications'),
        iconType: 'data_catalog',
        sceneKey: 'DataCatalog',
        group: 'data_catalog',
    },
    {
        key: 'data_catalog_usage',
        label: 'Usage',
        title: 'Data catalog usage',
        href: urls.dataCatalog('usage'),
        iconType: 'metrics',
        sceneKey: 'DataCatalog',
        group: 'data_catalog',
        flag: FEATURE_FLAGS.DATA_CATALOG_USAGE,
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
// The Sources pages are a product of their own, reached from the Source data page.
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

function hrefTab(href: string): string | null {
    return new URLSearchParams(href.split('?')[1] ?? '').get('tab')
}

/**
 * The menu item for the page at `path`: the one with the longest matching path. Items that share a path are the
 * tabs of one page, so `tab` picks between them and the item without a tab is the default.
 */
export function warehouseItemForLocation(
    path: string,
    items: WarehouseItem[],
    tab: string | null = null
): WarehouseItem | null {
    let matches: WarehouseItem[] = []
    let matchLength = -1
    for (const item of items) {
        for (const itemPath of itemPaths(item)) {
            if (!isUnder(path, itemPath) || itemPath.length < matchLength) {
                continue
            }
            if (itemPath.length > matchLength) {
                matches = []
                matchLength = itemPath.length
            }
            matches.push(item)
        }
    }
    return (
        matches.find((item) => hrefTab(item.href) === tab) ??
        matches.find((item) => hrefTab(item.href) === null) ??
        matches[0] ??
        null
    )
}
