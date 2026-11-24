import { urls } from 'scenes/urls'

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

function dataWarehouseSpecs(): TodayPaneProductSpec[] {
    return [{ href: urls.dataOps() }, { href: urls.models() }, { href: urls.dataWarehouseManagedViewsets() }]
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
