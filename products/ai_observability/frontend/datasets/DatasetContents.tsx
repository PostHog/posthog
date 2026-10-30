import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner } from '@posthog/lemon-ui'

import type { DatasetReadApi as Dataset } from '../generated/api.schemas'
import { DATASET_ITEM_VERSIONS_PER_PAGE, DatasetTab, aiObservabilityDatasetLogic } from './aiObservabilityDatasetLogic'
import { DatasetDetailsModal } from './DatasetDetailsModal'
import { DatasetItemModal } from './DatasetItemModal'
import { DatasetItems } from './DatasetItems'

export function DatasetContents({ dataset }: { dataset: Dataset }): JSX.Element {
    const {
        activeTab,
        isDatasetItemModalOpen,
        selectedDatasetItem,
        selectedDatasetItemLoadError,
        selectedDatasetItemDetailsLoading,
        selectedDatasetItemVersions,
        datasetItemVersionsLoading,
        datasetItemVersionsLoadError,
        datasetItemVersionsPage,
        restoringDatasetItemVersion,
        archivingDatasetItemId,
        canEditDataset,
        canManageDataset,
        isHistoricalRevision,
        filters,
        datasetExportLoading,
        datasetExportLoadError,
        datasetExportDisabledReason,
    } = useValues(aiObservabilityDatasetLogic)
    const {
        closeModalAndRefetchDatasetItems,
        loadDatasetItemDetails,
        restoreDatasetItem,
        restoreDatasetItemVersion,
        loadDatasetItemVersions,
        setFilters,
        setActiveTab,
        exportDataset,
    } = useActions(aiObservabilityDatasetLogic)
    const { searchParams } = useValues(router)
    const selectedItemReadOnly = !canEditDataset || !!selectedDatasetItem?.archived
    const selectedItemReadOnlyReason = isHistoricalRevision
        ? `You're viewing revision ${filters.revision}. Select Latest to edit items.`
        : dataset.archived
          ? 'This dataset is archived. Unarchive it to edit items.'
          : selectedDatasetItem?.archived
            ? 'This item is archived. Unarchive it to edit.'
            : !canManageDataset
              ? 'You have view-only access to this dataset.'
              : undefined

    return (
        <>
            {isHistoricalRevision && (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'View latest',
                        onClick: () => setFilters({ revision: null, page: 1 }, false),
                    }}
                >
                    This is a read-only snapshot of the dataset.
                </LemonBanner>
            )}
            {datasetExportLoadError && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => exportDataset(filters.revision ?? undefined),
                        loading: datasetExportLoading,
                        disabledReason: datasetExportDisabledReason,
                    }}
                >
                    {datasetExportLoadError.detail || "Couldn't add the dataset to exports. Try again."}
                </LemonBanner>
            )}
            <DatasetItems dataset={dataset} />
            <DatasetDetailsModal
                dataset={dataset}
                isOpen={activeTab === DatasetTab.Metadata && !isDatasetItemModalOpen}
                onClose={() => setActiveTab(DatasetTab.Items)}
            />

            <DatasetItemModal
                isOpen={isDatasetItemModalOpen}
                onClose={closeModalAndRefetchDatasetItems}
                partialDatasetItem={selectedDatasetItem}
                datasetId={dataset.id}
                displayBulkCreationButton
                readOnly={selectedItemReadOnly}
                readOnlyReason={selectedItemReadOnlyReason}
                loading={selectedDatasetItemDetailsLoading}
                loadError={selectedDatasetItemLoadError}
                versions={selectedDatasetItemVersions.results}
                versionsLoading={datasetItemVersionsLoading}
                versionsLoadError={datasetItemVersionsLoadError}
                versionsCount={selectedDatasetItemVersions.count}
                versionsPage={datasetItemVersionsPage}
                versionsPageSize={DATASET_ITEM_VERSIONS_PER_PAGE}
                canRestoreVersions={canEditDataset && !selectedDatasetItem?.archived}
                restoringVersion={restoringDatasetItemVersion}
                onRestoreVersion={restoreDatasetItemVersion}
                onVersionsPageChange={
                    selectedDatasetItem
                        ? (page) => loadDatasetItemVersions({ itemId: selectedDatasetItem.id, page })
                        : undefined
                }
                onRetryVersions={
                    selectedDatasetItem
                        ? () =>
                              loadDatasetItemVersions({
                                  itemId: selectedDatasetItem.id,
                                  page: datasetItemVersionsPage,
                              })
                        : undefined
                }
                onRetry={
                    searchParams.item
                        ? () =>
                              loadDatasetItemDetails({
                                  itemId: String(searchParams.item),
                                  revision: filters.revision ?? undefined,
                              })
                        : undefined
                }
                onUnarchive={
                    selectedDatasetItem?.archived && canManageDataset && !dataset.archived && !isHistoricalRevision
                        ? () => restoreDatasetItem(selectedDatasetItem.id, selectedDatasetItem.version)
                        : undefined
                }
                unarchiving={archivingDatasetItemId === selectedDatasetItem?.id}
            />
        </>
    )
}
