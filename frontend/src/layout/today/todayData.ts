import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { getNavProductPages } from '~/layout/panel-layout/navbar/tabs/navProductItems'

import {
    TodayPaneProduct,
    TodayPaneProductSpec,
    paneProductForPath,
    paneProductsFor,
    shownPaneProducts,
} from './todayPaneProducts'

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
        // Destinations stay here until an Automate pane takes them. Batch export pages live under /pipeline.
        { href: urls.destinations(), section: '/pipeline/batch-exports' },
        { href: urls.warehouseDestinations(), section: urls.warehouseDestinationConnect() },
        { href: urls.endpoints() },
    ]
}

function dataSetupSpecs(): TodayPaneProductSpec[] {
    return [{ href: urls.toolbarLaunch() }, { href: urls.wizardRuns() }]
}

export interface DataProducts {
    pipeline: TodayPaneProduct[]
    warehouse: TodayPaneProduct[]
    definitions: TodayPaneProduct[]
    outgoing: TodayPaneProduct[]
    setup: TodayPaneProduct[]
}

export function dataProducts(): DataProducts {
    const pages = getNavProductPages()
    return {
        pipeline: paneProductsFor(pages, dataPipelineSpecs()),
        warehouse: paneProductsFor(pages, dataWarehouseSpecs()),
        definitions: paneProductsFor(pages, dataDefinitionSpecs()),
        outgoing: paneProductsFor(pages, dataOutgoingSpecs()),
        setup: paneProductsFor(pages, dataSetupSpecs()),
    }
}

export function dataItems(featureFlags: FeatureFlagsSet): DataProducts {
    const { pipeline, warehouse, definitions, outgoing, setup } = dataProducts()
    return {
        pipeline: shownPaneProducts(pipeline, featureFlags),
        warehouse: shownPaneProducts(warehouse, featureFlags),
        definitions: shownPaneProducts(definitions, featureFlags),
        outgoing: shownPaneProducts(outgoing, featureFlags),
        setup: shownPaneProducts(setup, featureFlags),
    }
}

/** Matches against every Data product, shown or not, so a page keeps its pane while a flag hides its row. */
export function dataProductForPath(path: string): TodayPaneProduct | undefined {
    const { pipeline, warehouse, definitions, outgoing, setup } = dataProducts()
    return paneProductForPath([...pipeline, ...warehouse, ...definitions, ...outgoing, ...setup], path)
}

/** An event or property definition. Insights link to these, so an open Analytics pane keeps them as a drill-in. */
export function isDefinitionDetailPath(path: string): boolean {
    return /^\/data-management\/(events|properties)\/[^/]+$/.test(path)
}
