import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { combineUrl, router } from 'kea-router'
import { useEffect } from 'react'

import { IconArchive, IconDownload, IconPlusSmall } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonSegmentedButton,
    LemonSelect,
    LemonTab,
    LemonTabs,
    LemonTag,
    Link,
    ProfilePicture,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AccessDenied } from 'lib/components/AccessDenied'
import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { NotFound } from 'lib/components/NotFound'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { createdAtColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { toAccessControlLevel } from 'lib/utils/accessControlUtils'
import { isObject } from 'lib/utils/guards'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneTextarea } from '~/lib/components/Scenes/SceneTextarea'
import { SceneTextInput } from '~/lib/components/Scenes/SceneTextInput'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '~/lib/lemon-ui/LemonTable'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, type UserBasicType } from '~/types'

import type { DatasetItemReadApi as DatasetItem, DatasetReadApi as Dataset } from '../generated/api.schemas'
import { truncateValue } from '../utils'
import {
    DATASET_ITEM_VERSIONS_PER_PAGE,
    DatasetLogicProps,
    DatasetTab,
    isDataset,
    aiObservabilityDatasetLogic,
} from './aiObservabilityDatasetLogic'
import { getDatasetListUrl } from './aiObservabilityDatasetsLogic'
import { DatasetItemModal } from './DatasetItemModal'
import { EditDatasetForm } from './EditDatasetForm'
import { JSONColumn } from './JSONColumn'
import { RefreshButton } from './RefreshButton'

const RESOURCE_TYPE = 'dataset'

export const scene: SceneExport<DatasetLogicProps> = {
    component: AIObservabilityDatasetScene,
    logic: aiObservabilityDatasetLogic,
    productKey: ProductKey.AI_OBSERVABILITY,
    paramsToProps: ({ params: { id } }) => ({
        datasetId: id && id !== 'new' ? id : 'new',
    }),
}

export function AIObservabilityDatasetScene(): JSX.Element {
    const {
        shouldDisplaySkeleton,
        datasetLoading,
        isDatasetFormSubmitting,
        isEditingDataset,
        isDatasetMissing,
        isNewDataset,
        datasetForm,
        dataset,
        isArchivingDataset,
        canEditDataset,
        canManageDataset,
        isHistoricalRevision,
        filters,
        datasetExportLoading,
        datasetLoadError,
    } = useValues(aiObservabilityDatasetLogic)
    const {
        submitDatasetForm,
        loadDataset,
        editDataset,
        archiveDataset,
        restoreDataset,
        exportDataset,
        setDatasetFormValue,
        onUnmount,
    } = useActions(aiObservabilityDatasetLogic)
    const { searchParams } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]

    const displayEditForm = isNewDataset || (isEditingDataset && canEditDataset)
    const canChangeDatasetStatus = canManageDataset && !isHistoricalRevision
    const archiveOrRestoreDataset = (): void => {
        if (!canChangeDatasetStatus) {
            return
        }
        if (isDataset(dataset) && dataset.archived) {
            restoreDataset()
            return
        }
        LemonDialog.open({
            title: 'Archive dataset?',
            description: 'This removes it from the active datasets list.',
            primaryButton: {
                children: 'Archive',
                type: 'primary',
                status: 'danger',
                'data-attr': 'confirm-archive-dataset',
                onClick: archiveDataset,
            },
            secondaryButton: {
                children: 'Close',
                type: 'secondary',
            },
        })
    }

    // TRICKY: Scene logic is not unmounted. Workaround.
    useEffect(() => () => onUnmount(), [onUnmount])

    if (isDatasetMissing) {
        return <NotFound object="dataset" />
    }

    if (datasetLoadError?.status === 403) {
        return <AccessDenied object="dataset" />
    }

    if (datasetLoadError && !isDataset(dataset)) {
        return (
            <SceneContent>
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadDataset }}>
                    {datasetLoadError.detail || "Couldn't load this dataset. Try again."}
                </LemonBanner>
            </SceneContent>
        )
    }

    if (shouldDisplaySkeleton) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton active className="h-4 w-2/5" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-3/5" />
            </div>
        )
    }

    return (
        <Form id="dataset-form" formKey="datasetForm" logic={aiObservabilityDatasetLogic}>
            <SceneContent>
                {datasetLoadError && (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadDataset }}>
                        {datasetLoadError.detail || "Couldn't refresh this dataset. Try again."}
                    </LemonBanner>
                )}
                <SceneTitleSection
                    name={datasetForm.name}
                    resourceType={{ type: 'llm_analytics' }}
                    isLoading={datasetLoading}
                    actions={
                        !shouldDisplaySkeleton && displayEditForm ? (
                            <>
                                <LemonButton
                                    type="secondary"
                                    data-attr="cancel-dataset"
                                    onClick={() => {
                                        if (isEditingDataset) {
                                            editDataset(false)
                                            loadDataset()
                                        } else {
                                            router.actions.push(getDatasetListUrl(searchParams))
                                        }
                                    }}
                                    disabledReason={isDatasetFormSubmitting ? 'Saving…' : undefined}
                                    size="small"
                                >
                                    Cancel
                                </LemonButton>
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.LlmAnalytics}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={
                                        isDataset(dataset) ? toAccessControlLevel(dataset.user_access_level) : undefined
                                    }
                                >
                                    <LemonButton
                                        type="primary"
                                        data-attr="save-dataset"
                                        onClick={submitDatasetForm}
                                        loading={isDatasetFormSubmitting}
                                        size="small"
                                    >
                                        {isNewDataset ? 'Create dataset' : 'Save'}
                                    </LemonButton>
                                </AccessControlAction>
                            </>
                        ) : undefined
                    }
                />

                {isDataset(dataset) && sceneMenuBarEnabled && (
                    <SceneMenuBar>
                        <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                            <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />
                            <SceneMenuBarSeparator />
                            <SceneMenuBarItem
                                disabled={datasetExportLoading}
                                onClick={() => exportDataset(filters.revision ?? undefined)}
                                data-attr={`${RESOURCE_TYPE}-menubar-export`}
                            >
                                <IconDownload />
                                Export
                            </SceneMenuBarItem>
                            {canChangeDatasetStatus && (
                                <>
                                    <SceneMenuBarSeparator />
                                    <SceneMenuBarItem
                                        variant={dataset.archived ? undefined : 'destructive'}
                                        disabled={datasetLoading || isArchivingDataset}
                                        onClick={archiveOrRestoreDataset}
                                        data-attr={`${RESOURCE_TYPE}-menubar-${
                                            dataset.archived ? 'unarchive' : 'archive'
                                        }`}
                                    >
                                        <IconArchive />
                                        {dataset.archived ? 'Unarchive' : 'Archive'}
                                    </SceneMenuBarItem>
                                </>
                            )}
                        </SceneMenuBarMenu>
                    </SceneMenuBar>
                )}
                {isDataset(dataset) && (
                    <ScenePanel>
                        <ScenePanelInfoSection>
                            <SceneTextInput
                                name="name"
                                defaultValue={datasetForm.name}
                                onSave={(value) => {
                                    setDatasetFormValue('name', value)
                                    submitDatasetForm()
                                }}
                                dataAttrKey={RESOURCE_TYPE}
                                isLoading={datasetLoading || isDatasetFormSubmitting}
                                canEdit={canEditDataset}
                            />
                            <SceneTextarea
                                name="description"
                                defaultValue={datasetForm.description}
                                onSave={(value) => {
                                    setDatasetFormValue('description', value)
                                    submitDatasetForm()
                                }}
                                dataAttrKey={RESOURCE_TYPE}
                                optional
                                isLoading={datasetLoading || isDatasetFormSubmitting}
                                canEdit={canEditDataset}
                            />
                        </ScenePanelInfoSection>
                        <ScenePanelDivider />
                        <ScenePanelActionsSection>
                            <ScenePanelDivider />
                            {canChangeDatasetStatus && (
                                <ButtonPrimitive
                                    onClick={archiveOrRestoreDataset}
                                    variant={dataset.archived ? undefined : 'danger'}
                                    menuItem
                                    data-attr={`${RESOURCE_TYPE}-${dataset.archived ? 'unarchive' : 'archive'}`}
                                    disabledReasons={{
                                        'Dataset is loading': datasetLoading,
                                        'Dataset status is changing': isArchivingDataset,
                                    }}
                                >
                                    <IconArchive />
                                    {dataset.archived ? 'Unarchive' : 'Archive'}
                                </ButtonPrimitive>
                            )}
                        </ScenePanelActionsSection>
                    </ScenePanel>
                )}

                {displayEditForm ? <EditDatasetForm /> : isDataset(dataset) ? <DatasetTabs dataset={dataset} /> : null}
            </SceneContent>
        </Form>
    )
}

function DatasetTabs({ dataset }: { dataset: Dataset }): JSX.Element {
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
    } = useValues(aiObservabilityDatasetLogic)
    const {
        closeModalAndRefetchDatasetItems,
        loadDatasetItemDetails,
        restoreDatasetItem,
        restoreDatasetItemVersion,
        loadDatasetItemVersions,
        setFilters,
        exportDataset,
        editDataset,
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

    const tabs: LemonTab<DatasetTab>[] = [
        {
            key: DatasetTab.Items,
            label: 'Items',
            content: <DatasetItems dataset={dataset} />,
            link: combineUrl(urls.aiObservabilityDataset(dataset.id), { ...searchParams, tab: DatasetTab.Items }).url,
        },
        {
            key: DatasetTab.Metadata,
            label: 'Metadata',
            content: <DatasetMetadata dataset={dataset} />,
            link: combineUrl(urls.aiObservabilityDataset(dataset.id), { ...searchParams, tab: DatasetTab.Metadata })
                .url,
        },
    ]

    return (
        <>
            <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                        <LemonTag type={dataset.archived ? 'muted' : 'success'}>
                            {dataset.archived ? 'Archived' : 'Active'}
                        </LemonTag>
                        {isHistoricalRevision && <LemonTag type="default">Revision {filters.revision}</LemonTag>}
                    </div>
                    {canEditDataset && (
                        <LemonButton
                            type="secondary"
                            onClick={() => editDataset(true)}
                            data-attr="edit-dataset"
                            size="small"
                        >
                            Edit
                        </LemonButton>
                    )}
                </div>
                <p className="m-0">{dataset.description || <span className="italic">Description (optional)</span>}</p>
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
                        }}
                    >
                        {datasetExportLoadError.detail || "Couldn't add the dataset to exports. Try again."}
                    </LemonBanner>
                )}
            </div>

            <LemonTabs activeKey={activeTab} data-attr="dataset-tabs" tabs={tabs} />

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

function DatasetItems({ dataset }: { dataset: Dataset }): JSX.Element {
    const {
        archivingDatasetItemId,
        datasetItems,
        datasetItemsLoading,
        datasetItemsLoadError,
        datasetRevisionsLoading,
        datasetRevisionsLoadError,
        pagination,
        filters,
        revisionOptions,
        canEditDataset,
        canManageDataset,
        isHistoricalRevision,
        isArchivingDataset,
        datasetExportLoading,
    } = useValues(aiObservabilityDatasetLogic)
    const {
        archiveDatasetItem,
        restoreDatasetItem,
        loadDatasetItems,
        loadDatasetRevisions,
        setFilters,
        restoreDataset,
        exportDataset,
        triggerDatasetItemModal,
    } = useActions(aiObservabilityDatasetLogic)
    const { searchParams } = useValues(router)
    const canChangeDatasetStatus = canManageDataset && !isHistoricalRevision

    const columns: LemonTableColumns<DatasetItem> = [
        {
            title: 'ID',
            dataIndex: 'id',
            key: 'id',
            width: '10%',
            render: function renderID(_, item) {
                return (
                    <Link to={urls.aiObservabilityDataset(dataset.id, { ...searchParams, item: item.id })}>
                        {truncateValue(item.id)}
                    </Link>
                )
            },
        },
        {
            title: 'Trace',
            dataIndex: 'source_trace_id',
            key: 'source_trace_id',
            width: '10%',
            render: function renderSourceTraceId(_, item) {
                if (!item.source_trace_id || !item.source_timestamp) {
                    return <span>-</span>
                }

                return (
                    <Link
                        to={urls.aiObservabilityTrace(item.source_trace_id, {
                            event: item.source_event_id ?? undefined,
                            timestamp: item.source_timestamp,
                        })}
                    >
                        {truncateValue(item.source_trace_id)}
                    </Link>
                )
            },
        },
        {
            title: 'Input',
            dataIndex: 'input',
            key: 'input',
            width: '20%',
            render: function renderInput(_, item) {
                return <JSONColumn>{item.input}</JSONColumn>
            },
        },
        {
            title: 'Expected output',
            dataIndex: 'expected_output',
            key: 'expected_output',
            width: '20%',
            render: function renderExpectedOutput(_, item) {
                return <JSONColumn>{item.expected_output}</JSONColumn>
            },
        },
        {
            title: 'Source output',
            dataIndex: 'source_output',
            key: 'source_output',
            width: '20%',
            render: function renderSourceOutput(_, item) {
                return <JSONColumn>{item.source_output}</JSONColumn>
            },
        },
        {
            title: 'Metadata',
            dataIndex: 'metadata',
            key: 'metadata',
            width: '25%',
            render: function renderMetadata(_, item) {
                return <JSONColumn>{item.metadata}</JSONColumn>
            },
        },
        {
            title: 'Created by',
            dataIndex: 'created_by',
            render: function renderCreatedBy(_, item) {
                const { created_by } = item
                return (
                    <div className="flex flex-row items-center flex-nowrap">
                        {created_by && <ProfilePicture user={created_by as UserBasicType} size="md" showName />}
                    </div>
                )
            },
        },
        {
            title: 'Status',
            key: 'status',
            render: function renderStatus(_, item) {
                return (
                    <LemonTag type={item.archived ? 'muted' : 'success'}>
                        {item.archived ? 'Archived' : 'Active'}
                    </LemonTag>
                )
            },
        },
        createdAtColumn<DatasetItem>() as LemonTableColumn<DatasetItem, keyof DatasetItem | undefined>,
        updatedAtColumn<DatasetItem>() as LemonTableColumn<DatasetItem, keyof DatasetItem | undefined>,
        {
            width: 0,
            render: function renderMore(_, item) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    to={urls.aiObservabilityDataset(dataset.id, { ...searchParams, item: item.id })}
                                    data-attr={`dataset-item-${item.id}-dropdown-edit`}
                                    fullWidth
                                >
                                    {canEditDataset && !item.archived ? 'Edit' : 'View'}
                                </LemonButton>

                                {canManageDataset && !dataset.archived && !isHistoricalRevision && (
                                    <LemonButton
                                        status={item.archived ? undefined : 'danger'}
                                        onClick={() =>
                                            item.archived
                                                ? restoreDatasetItem(item.id, item.version)
                                                : archiveDatasetItem(item.id, item.version)
                                        }
                                        loading={archivingDatasetItemId === item.id}
                                        disabledReason={
                                            archivingDatasetItemId && archivingDatasetItemId !== item.id
                                                ? 'Another dataset item is being archived'
                                                : undefined
                                        }
                                        data-attr={`dataset-item-${item.id}-dropdown-${
                                            item.archived ? 'unarchive' : 'archive'
                                        }`}
                                        fullWidth
                                    >
                                        {item.archived ? 'Unarchive' : 'Archive'}
                                    </LemonButton>
                                )}
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <>
            <div className="flex justify-between items-center gap-2 flex-wrap">
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonSegmentedButton
                        value={filters.archived ? 'archived' : 'active'}
                        onChange={(value) => setFilters({ archived: value === 'archived', page: 1 }, false)}
                        options={[
                            { value: 'active', label: 'Active' },
                            { value: 'archived', label: 'Archived' },
                        ]}
                        size="small"
                        data-attr="dataset-items-status-filter"
                    />
                    <LemonSelect
                        value={filters.revision === null ? 'latest' : String(filters.revision)}
                        onChange={(value) =>
                            setFilters({ revision: value === 'latest' ? null : Number(value), page: 1 }, false)
                        }
                        options={revisionOptions}
                        loading={datasetRevisionsLoading}
                        size="small"
                        data-attr="dataset-revision-select"
                    />
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <RefreshButton
                        onClick={() => {
                            loadDatasetItems(true)
                        }}
                        isRefreshing={datasetItemsLoading}
                    />
                    <LemonButton
                        type="secondary"
                        onClick={() => exportDataset(filters.revision ?? undefined)}
                        loading={datasetExportLoading}
                        data-attr="export-dataset"
                        icon={<IconDownload />}
                        size="small"
                    >
                        Export
                    </LemonButton>
                    {canEditDataset && (
                        <LemonButton
                            type="primary"
                            onClick={() => triggerDatasetItemModal(true)}
                            data-attr="add-dataset-item"
                            icon={<IconPlusSmall />}
                            size="small"
                        >
                            Add item
                        </LemonButton>
                    )}
                    {dataset.archived && canChangeDatasetStatus && (
                        <LemonButton
                            type="primary"
                            onClick={restoreDataset}
                            loading={isArchivingDataset}
                            data-attr="unarchive-dataset"
                            size="small"
                        >
                            Unarchive
                        </LemonButton>
                    )}
                </div>
            </div>

            {datasetItemsLoadError && (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadDatasetItems(false) }}>
                    {datasetItemsLoadError.detail || "Couldn't load dataset items. Try again."}
                </LemonBanner>
            )}

            {datasetRevisionsLoadError && (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadDatasetRevisions }}>
                    {datasetRevisionsLoadError.detail || "Couldn't load dataset revisions. Try again."}
                </LemonBanner>
            )}

            <LemonDivider className="my-4" />

            <LemonTable
                loading={datasetItemsLoading}
                columns={columns}
                dataSource={datasetItems?.results || []}
                rowKey="id"
                pagination={pagination}
                nouns={['dataset item', 'dataset items']}
                emptyState="No items in this dataset yet."
            />
        </>
    )
}

function DatasetMetadata({ dataset }: { dataset: Dataset }): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-160">
            <div className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold m-0">Metadata</h3>
                {isObject(dataset.metadata) ? (
                    <div className="bg-bg-light p-4 rounded border overflow-x-auto">
                        <HighlightedJSONViewer src={dataset.metadata} />
                    </div>
                ) : (
                    <p className="text-muted m-0">No metadata available.</p>
                )}
            </div>
        </div>
    )
}
