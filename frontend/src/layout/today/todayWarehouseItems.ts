import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { DEFINITIONS_TABS } from 'scenes/data-management/definitionsSceneTabsLogic'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

export type WarehouseItemKey =
    | 'home'
    | 'etl'
    | 'sources'
    | 'managed_migrations'
    | 'event_filtering'
    | 'ingestion_warnings'
    | 'sql_editor'
    | 'models'
    | 'transformations'
    | 'managed_viewsets'
    | 'warehouse_destinations'
    | 'destinations'
    | 'endpoints'
    | 'data_catalog'
    | 'definitions'
    | 'actions'
    | 'sql_variables'
    | 'data_ops'

export interface WarehouseItem {
    // pinned: sent as the `item` and `from` properties of `warehouse menu item clicked`, and part of each menu row's data-attr.
    key: WarehouseItemKey
    label: string
    href: string
    iconType: FileSystemIconType
    sceneKey: string
    group: 'home' | 'import' | 'transform' | 'export' | 'define' | 'manage'
    flag?: FeatureFlagKey
    // Pages reached from this item that live under another prefix, such as batch exports under `/pipeline`.
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
        key: 'etl',
        label: 'ELT',
        href: urls.etlOverview(),
        iconType: 'data_pipeline',
        sceneKey: 'PipelineOverview',
        group: 'home',
        flag: FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION,
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
        key: 'managed_migrations',
        label: 'Managed migrations',
        href: urls.managedMigration(),
        iconType: 'managed_migration',
        sceneKey: 'ManagedMigration',
        group: 'import',
    },
    {
        key: 'event_filtering',
        label: 'Event ingestion filtering',
        href: urls.eventFiltering(),
        iconType: 'event_filter',
        sceneKey: 'EventFiltering',
        group: 'import',
    },
    {
        key: 'ingestion_warnings',
        label: 'Event ingestion warnings',
        href: urls.ingestionWarnings(),
        iconType: 'ingestion_warning',
        sceneKey: 'DataManagement',
        group: 'import',
        extraPaths: [urls.ingestionWarningsV2()],
    },
    {
        key: 'sql_editor',
        label: 'SQL editor',
        href: urls.sqlEditor(),
        iconType: 'sql_editor',
        sceneKey: 'SQLEditor',
        group: 'transform',
    },
    {
        key: 'models',
        label: 'Models',
        href: urls.models(),
        iconType: 'data_modeling',
        sceneKey: 'Models',
        group: 'transform',
    },
    {
        key: 'transformations',
        label: 'Transformations',
        href: urls.transformations(),
        iconType: 'data_transformation',
        sceneKey: 'Transformations',
        group: 'transform',
    },
    {
        key: 'managed_viewsets',
        label: 'Managed viewsets',
        href: urls.dataWarehouseManagedViewsets(),
        iconType: 'managed_viewsets',
        sceneKey: 'DataManagement',
        group: 'transform',
        flag: FEATURE_FLAGS.MANAGED_VIEWSETS,
    },
    {
        key: 'warehouse_destinations',
        label: 'Warehouse destinations',
        href: urls.warehouseDestinations(),
        iconType: 'warehouse_destination',
        sceneKey: 'WarehouseDestinations',
        group: 'export',
        flag: FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION,
    },
    {
        key: 'destinations',
        label: 'Destinations',
        href: urls.destinations(),
        iconType: 'data_destination',
        sceneKey: 'Destinations',
        group: 'export',
        extraPaths: ['/pipeline/batch-exports'],
    },
    {
        key: 'endpoints',
        label: 'Endpoints',
        href: urls.endpoints(),
        iconType: 'endpoints',
        sceneKey: 'EndpointsScene',
        group: 'export',
    },
    {
        key: 'data_catalog',
        label: 'Data catalog',
        href: urls.dataCatalog(),
        iconType: 'data_catalog',
        sceneKey: 'DataCatalog',
        group: 'define',
    },
    {
        key: 'definitions',
        label: 'Definitions',
        href: urls.eventDefinitions(),
        iconType: 'event_definition',
        sceneKey: 'DataManagement',
        group: 'define',
        extraPaths: DEFINITIONS_TABS.map((tab) => tab.url).filter((url) => url !== urls.eventDefinitions()),
    },
    {
        key: 'actions',
        label: 'Actions',
        href: urls.actions(),
        iconType: 'action',
        sceneKey: 'Actions',
        group: 'define',
    },
    {
        key: 'sql_variables',
        label: 'SQL variables',
        href: urls.variables(),
        iconType: 'sql_variable',
        sceneKey: 'DataManagement',
        group: 'define',
    },
    {
        key: 'data_ops',
        label: 'Data ops',
        href: urls.dataOps(),
        iconType: 'data_warehouse',
        sceneKey: 'DataOps',
        group: 'manage',
        flag: FEATURE_FLAGS.DATA_WAREHOUSE_SCENE,
    },
]

// Warehouse pages that no menu item names: the new-source wizard and the connect flow under `/data-warehouse`,
// and the function pages under `/functions` and `/pipeline/new`. Destinations, transformations, webhook sources
// and web scripts share those function routes, so the routes map to the warehouse pane but to no single item.
const EXTRA_WAREHOUSE_PATHS = ['/data-warehouse', '/functions', '/pipeline/new']

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
            (!item.flag || !!featureFlags[item.flag as keyof FeatureFlagsSet]) &&
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
