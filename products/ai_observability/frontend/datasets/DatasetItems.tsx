import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconDownload, IconPlusSmall } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonSegmentedButton,
    LemonSelect,
    LemonTag,
    Link,
    ProfilePicture,
} from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { urls } from 'scenes/urls'

import { UserBasicType } from '~/types'

import type { DatasetItemReadApi as DatasetItem, DatasetReadApi as Dataset } from '../generated/api.schemas'
import { truncateValue } from '../utils'
import { aiObservabilityDatasetLogic } from './aiObservabilityDatasetLogic'
import { JSONColumn } from './JSONColumn'
import { RefreshButton } from './RefreshButton'

export function DatasetItems({ dataset }: { dataset: Dataset }): JSX.Element {
    const {
        archivingDatasetItemId,
        datasetItems,
        datasetLoading,
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
        datasetExportDisabledReason,
    } = useValues(aiObservabilityDatasetLogic)
    const {
        archiveDatasetItem,
        restoreDatasetItem,
        loadDatasetItems,
        loadDatasetRevisions,
        refreshDataset,
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
                    <LemonTag size="small" type={item.archived ? 'muted' : 'success'}>
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
        <div className="flex flex-col gap-3">
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
                        onClick={refreshDataset}
                        isRefreshing={datasetItemsLoading || datasetLoading || datasetRevisionsLoading}
                    />
                    <LemonButton
                        type="secondary"
                        onClick={() => exportDataset(filters.revision ?? undefined)}
                        loading={datasetExportLoading}
                        disabledReason={datasetExportDisabledReason}
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

            <LemonTable
                size="small"
                loading={datasetItemsLoading}
                columns={columns}
                dataSource={datasetItems?.results || []}
                rowKey="id"
                pagination={pagination}
                nouns={['dataset item', 'dataset items']}
                emptyState="No items in this dataset yet."
            />
        </div>
    )
}
