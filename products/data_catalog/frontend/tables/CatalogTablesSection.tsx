import { useActions, useValues } from 'kea'

import { Skeleton, Text } from '@posthog/quill'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { ModelsOverviewErrorCallout } from 'products/data_modeling/frontend/ModelsOverviewErrorCallout'
import { modelsOverviewLogic } from 'products/data_modeling/frontend/modelsOverviewLogic'
import {
    CHECKS_LIMIT,
    dataQualityOverviewLogic,
} from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { catalogTablesLogic } from '../catalogTablesLogic'
import { certificationsLogic } from '../certificationsLogic'
import { CatalogTablesBulkBar } from './CatalogTablesBulkBar'
import { CatalogTablesSuggestions } from './CatalogTablesSuggestions'
import { CatalogTablesTable } from './CatalogTablesTable'
import { CatalogTablesToolbar } from './CatalogTablesToolbar'

const SKELETON_ROWS = 5

function LoadingRows(): JSX.Element {
    return (
        <div className="flex flex-col gap-2" aria-busy="true">
            {Array.from({ length: SKELETON_ROWS }, (_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
            ))}
        </div>
    )
}

function LoadErrors(): JSX.Element {
    const { modelsFailed } = useValues(modelsOverviewLogic)
    const { overviewError, snapshotLoaded, checksTruncated } = useValues(dataQualityOverviewLogic)
    const { loadNodes, loadDataWarehouseSavedQueries, loadOverview } = useActions(modelsOverviewLogic)
    const { certificationsLoadFailed } = useValues(catalogTablesLogic)
    const { loadCertifications } = useActions(certificationsLogic)
    return (
        <>
            {certificationsLoadFailed && (
                <ModelsOverviewErrorCallout
                    message="Certifications could not be loaded, so trust marks are not shown and can't be changed."
                    onRetry={loadCertifications}
                    dataAttr="data-catalog-tables-certifications-error"
                />
            )}
            {modelsFailed && (
                <ModelsOverviewErrorCallout
                    message="Refresh status for your views could not be loaded, so refresh problems are not shown."
                    onRetry={() => {
                        loadNodes()
                        loadDataWarehouseSavedQueries()
                    }}
                    dataAttr="data-catalog-tables-models-error"
                />
            )}
            {snapshotLoaded && overviewError && (
                <ModelsOverviewErrorCallout
                    message="Data quality checks could not be refreshed, so the checks shown may be out of date."
                    onRetry={() => loadOverview()}
                    dataAttr="data-catalog-tables-checks-error"
                />
            )}
            {checksTruncated && (
                <Text size="xs" variant="muted" data-attr="data-catalog-tables-checks-truncated">
                    Only the first {CHECKS_LIMIT} checks are loaded. Check counts cover every check, but failing checks
                    past that limit don't show as problems.
                </Text>
            )}
        </>
    )
}

function TablesContent(): JSX.Element {
    const { rowsLoaded, rowsError, selectedRows } = useValues(catalogTablesLogic)
    const { loadDatabase } = useActions(databaseTableListLogic)
    const { loadOverview } = useActions(dataQualityOverviewLogic)

    if (!rowsLoaded && rowsError) {
        return (
            <ModelsOverviewErrorCallout
                message="Your tables could not be loaded. Try again, and if it keeps failing, refresh the page."
                onRetry={() => {
                    loadDatabase()
                    loadOverview()
                }}
                dataAttr="data-catalog-tables-error"
            />
        )
    }
    if (!rowsLoaded) {
        return <LoadingRows />
    }
    return (
        <>
            <LoadErrors />
            <CatalogTablesTable />
            {selectedRows.length > 0 && <CatalogTablesBulkBar />}
        </>
    )
}

export function CatalogTablesSection(): JSX.Element {
    return (
        <section aria-label="Tables and views" className="flex flex-col gap-3" data-attr="data-catalog-tables">
            <CatalogTablesSuggestions />
            <CatalogTablesToolbar />
            <TablesContent />
        </section>
    )
}
