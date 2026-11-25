import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemImport } from '~/queries/schema/schema-general'

import { TODAY_DATA_RECENT_TYPES } from './todayDataRecents'
import type { TodayPaneProductSpec, TodayProductPaneConfig } from './todayPaneProducts'

function dataPipelineSpecs(): TodayPaneProductSpec[] {
    return [
        // The new-source and connect pages live under /data-warehouse, apart from the Sources list.
        { href: urls.sources(), section: '/data-warehouse' },
        { href: urls.etlOverview() },
        { href: urls.transformations() },
        { href: urls.eventFiltering() },
        { href: urls.managedMigration() },
    ]
}

// The warehouse console pages are not in the product list, so each row carries its own entry and flag.
function warehouseConsolePage(
    path: string,
    href: string,
    sceneKey: string,
    // pinned: autocapture `data-attr` suffix, `data-sidebar-warehouse-<key>`.
    key: string
): TodayPaneProductSpec & { item: FileSystemImport } {
    return {
        href,
        key,
        item: { path, iconType: 'data_warehouse', href, flag: FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE, sceneKey },
    }
}

function dataWarehouseSpecs(): TodayPaneProductSpec[] {
    return [
        { href: urls.dataOps() },
        { href: urls.models() },
        { href: urls.dataWarehouseManagedViewsets() },
        warehouseConsolePage(
            'PostHog data',
            urls.warehousePostHogData(),
            'WarehousePostHogData',
            'warehouse-posthog-data'
        ),
        warehouseConsolePage('Source data', urls.warehouseSourceData(), 'WarehouseSourceData', 'warehouse-source-data'),
        warehouseConsolePage('Usage', urls.warehouseUsage(), 'WarehouseUsage', 'warehouse-usage'),
        warehouseConsolePage('Queries', urls.warehouseQueries(), 'WarehouseQueries', 'warehouse-queries'),
        warehouseConsolePage('Storage', urls.warehouseStorage(), 'WarehouseStorage', 'warehouse-storage'),
        warehouseConsolePage('Access', urls.warehouseAccess(), 'WarehouseAccess', 'warehouse-access'),
        warehouseConsolePage('Connect', urls.warehouseConnect(), 'WarehouseConnect', 'warehouse-connect'),
        {
            ...warehouseConsolePage('Settings', urls.warehouseSettings(), 'WarehouseSettings', 'warehouse-settings'),
            // The upsell page at /warehouse sends people to setup, so it opens the Data pane with this row active.
            section: urls.warehouse(),
        },
    ]
}

function dataDefinitionSpecs(): TodayPaneProductSpec[] {
    return [
        { href: urls.dataCatalog() },
        { href: urls.eventDefinitions() },
        { href: urls.propertyDefinitions() },
        { href: urls.schemaManagement() },
        { href: urls.coreEvents() },
        { href: urls.actions() },
        { href: urls.revenueSettings() },
        { href: urls.warehouseProperties() },
        { href: urls.variables() },
    ]
}

function dataOutgoingSpecs(): TodayPaneProductSpec[] {
    return [
        { href: urls.warehouseDestinations(), section: urls.warehouseDestinationConnect() },
        { href: urls.endpoints() },
    ]
}

function dataSetupSpecs(): TodayPaneProductSpec[] {
    return [{ href: urls.toolbarLaunch() }, { href: urls.wizardRuns() }]
}

export const DATA_PANE: TodayProductPaneConfig = {
    pane: 'data',
    label: 'Data',
    lead: { id: 'pipeline', rowDataAttr: 'data-sidebar-pipeline', specs: dataPipelineSpecs },
    sections: [
        { id: 'warehouse', label: 'Warehouse', rowDataAttr: 'data-sidebar-warehouse', specs: dataWarehouseSpecs },
        {
            id: 'definitions',
            label: 'Definitions',
            rowDataAttr: 'data-sidebar-definitions',
            specs: dataDefinitionSpecs,
        },
        { id: 'outgoing', label: 'Outgoing', rowDataAttr: 'data-sidebar-outgoing', specs: dataOutgoingSpecs },
        { id: 'setup', label: 'Setup', rowDataAttr: 'data-sidebar-setup', specs: dataSetupSpecs },
    ],
    recentTypes: TODAY_DATA_RECENT_TYPES,
    recentTypeInfo: {
        event_definition: {
            iconType: 'event_definition',
            label: 'Event',
            description: 'An event definition. Open it to see its description, properties, and where it is used.',
        },
        property_definition: {
            iconType: 'property_definition',
            label: 'Property',
            description: 'A property definition. Open it to see its type, description, and where it is used.',
        },
        data_source: {
            iconType: 'data_source',
            label: 'Source',
            description: 'A data source. Open it to see its tables, syncs, and settings.',
        },
        data_model: {
            iconType: 'data_modeling',
            label: 'Table',
            description: 'A table or view in your warehouse. Open it to see its columns, lineage, and data quality.',
        },
    },
}

/** An event or property definition. Insights link to these, so an open Analytics pane keeps them as a drill-in. */
export function isDefinitionDetailPath(path: string): boolean {
    return /^\/data-management\/(events|properties)\/[^/]+$/.test(path)
}
