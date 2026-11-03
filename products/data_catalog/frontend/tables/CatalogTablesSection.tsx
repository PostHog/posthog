import { BindLogic, useActions, useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { AccessControlObjectModal } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlObjectModal'
import { AccessControlResourceType } from '~/types'

import { ModelsOverviewErrorCallout } from 'products/data_modeling/frontend/ModelsOverviewErrorCallout'
import { modelsOverviewLogic } from 'products/data_modeling/frontend/modelsOverviewLogic'
import { viewsTabLogic } from 'products/data_modeling/frontend/viewsTabLogic'
import { CheckEditorModal } from 'products/data_quality/frontend/CheckEditorModal'
import { dataQualityCheckEditorLogic } from 'products/data_quality/frontend/dataQualityCheckEditorLogic'
import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'
import { overviewCheckEditorProps } from 'products/data_quality/frontend/overview/overviewCheckEditorProps'
import { RunAllBanners } from 'products/data_quality/frontend/overview/RunAllBanners'

import { catalogTablesLogic } from '../catalogTablesLogic'
import { NewCertificationModal } from '../components/NewCertificationModal'
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

function ViewsAccessControlModal(): JSX.Element | null {
    const { editingAccessControlView, accessControlModalOpen } = useValues(viewsTabLogic)
    const { closeAccessControlModal } = useActions(viewsTabLogic)
    if (!editingAccessControlView) {
        return null
    }
    return (
        <AccessControlObjectModal
            isOpen={accessControlModalOpen}
            onClose={closeAccessControlModal}
            resource={AccessControlResourceType.WarehouseView}
            resource_id={editingAccessControlView.id}
            title={editingAccessControlView.name}
            description="Control who can query this view. Users without access won't see it and queries referencing it will fail for them."
        />
    )
}

function LoadErrors(): JSX.Element {
    const { modelsFailed } = useValues(modelsOverviewLogic)
    const { overviewError, snapshotLoaded } = useValues(dataQualityOverviewLogic)
    const { loadNodes, loadDataWarehouseSavedQueries, loadOverview } = useActions(modelsOverviewLogic)
    return (
        <>
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
        </>
    )
}

function TablesContent(): JSX.Element {
    const { rowsLoaded, rowsError } = useValues(catalogTablesLogic)
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
            <RunAllBanners />
            <CatalogTablesTable />
        </>
    )
}

export function CatalogTablesSection(): JSX.Element {
    const { lastActionCheckId } = useValues(dataQualityOverviewLogic)
    const { loadOverview, runChecks } = useActions(dataQualityOverviewLogic)
    const editorProps = overviewCheckEditorProps({ lastActionCheckId, loadOverview, runChecks })

    return (
        <BindLogic logic={dataQualityCheckEditorLogic} props={editorProps}>
            <section aria-label="Tables and views" className="flex flex-col gap-3" data-attr="data-catalog-tables">
                <CatalogTablesToolbar />
                <TablesContent />
            </section>
            <CheckEditorModal />
            <NewCertificationModal />
            <ViewsAccessControlModal />
        </BindLogic>
    )
}
