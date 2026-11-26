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
        { href: urls.tagDefinitions() },
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
}

/** An event or property definition. Insights link to these, so an open Analytics pane keeps them as a drill-in. */
export function isDefinitionDetailPath(path: string): boolean {
    return /^\/data-management\/(events|properties)\/[^/]+$/.test(path)
}
