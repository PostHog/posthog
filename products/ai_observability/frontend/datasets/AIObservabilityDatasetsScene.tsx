import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { LemonInput } from '~/lib/lemon-ui/LemonInput'
import { LemonSegmentedButton } from '~/lib/lemon-ui/LemonSegmentedButton'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '~/lib/lemon-ui/LemonTable'
import { createdAtColumn, updatedAtColumn } from '~/lib/lemon-ui/LemonTable/columnUtils'
import { LemonTag } from '~/lib/lemon-ui/LemonTag'
import { toAccessControlLevel } from '~/lib/utils/accessControlUtils'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, type UserBasicType } from '~/types'

import type { DatasetReadApi as Dataset } from '../generated/api.schemas'
import { DATASETS_PER_PAGE, aiObservabilityDatasetsLogic, getDatasetDetailUrl } from './aiObservabilityDatasetsLogic'

export const scene: SceneExport = {
    component: AIObservabilityDatasetsScene,
    logic: aiObservabilityDatasetsLogic,
    productKey: ProductKey.AI_OBSERVABILITY,
}

export function AIObservabilityDatasetsScene(): JSX.Element {
    const { setFilters, archiveDataset, restoreDataset } = useActions(aiObservabilityDatasetsLogic)
    const { archivingDatasetId, datasets, datasetsLoading, sorting, pagination, filters, datasetCountLabel } =
        useValues(aiObservabilityDatasetsLogic)
    const { searchParams } = useValues(router)
    const datasetUrl = (id: string): string => getDatasetDetailUrl(id, searchParams)

    const columns: LemonTableColumns<Dataset> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            width: '20%',
            render: function renderName(_, dataset) {
                return (
                    <Link to={datasetUrl(dataset.id)} data-testid="dataset-link">
                        {dataset.name}
                    </Link>
                )
            },
        },
        {
            title: 'Description',
            dataIndex: 'description',
            key: 'description',
            width: '50%',
            render: function renderDescription(description) {
                return <span className="text-muted">{String(description) || <i>–</i>}</span>
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
            render: function renderStatus(_, dataset) {
                return (
                    <LemonTag type={dataset.archived ? 'muted' : 'success'}>
                        {dataset.archived ? 'Archived' : 'Active'}
                    </LemonTag>
                )
            },
        },
        createdAtColumn<Dataset>() as LemonTableColumn<Dataset, keyof Dataset | undefined>,
        updatedAtColumn<Dataset>() as LemonTableColumn<Dataset, keyof Dataset | undefined>,
        {
            width: 0,
            render: function renderMore(_, dataset) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    to={datasetUrl(dataset.id)}
                                    data-attr={`dataset-item-${dataset.id}-dropdown-view`}
                                    fullWidth
                                >
                                    View
                                </LemonButton>

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.LlmAnalytics}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={toAccessControlLevel(dataset.user_access_level)}
                                >
                                    <LemonButton
                                        status={dataset.archived ? undefined : 'danger'}
                                        onClick={() =>
                                            dataset.archived ? restoreDataset(dataset.id) : archiveDataset(dataset.id)
                                        }
                                        loading={archivingDatasetId === dataset.id}
                                        disabledReason={
                                            archivingDatasetId && archivingDatasetId !== dataset.id
                                                ? 'Another dataset is being archived'
                                                : undefined
                                        }
                                        data-attr={`dataset-${dataset.id}-dropdown-${
                                            dataset.archived ? 'unarchive' : 'archive'
                                        }`}
                                        fullWidth
                                    >
                                        {dataset.archived ? 'Unarchive' : 'Archive'}
                                    </LemonButton>
                                </AccessControlAction>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Datasets"
                description="Create and manage datasets to test changes and evaluate your AI outputs. [Learn more](https://posthog.com/docs/ai-evals/datasets)"
                markdown
                resourceType={{ type: 'llm_datasets' }}
            />
            <div className="flex gap-x-4 gap-y-2 items-center flex-wrap py-4 -mt-4 mb-4 border-b justify-between">
                <div className="flex gap-2 items-center flex-wrap">
                    <LemonSegmentedButton
                        value={filters.archived ? 'archived' : 'active'}
                        onChange={(value) => setFilters({ archived: value === 'archived' }, true, false)}
                        options={[
                            { value: 'active', label: 'Active' },
                            { value: 'archived', label: 'Archived' },
                        ]}
                        size="small"
                        data-attr="datasets-status-filter"
                    />
                    <LemonInput
                        type="search"
                        placeholder="Search datasets..."
                        value={filters.search}
                        data-attr="datasets-search-input"
                        onChange={(value) => setFilters({ search: value })}
                        className="max-w-md"
                        data-testid="search-datasets-input"
                    />
                </div>
                <div className="flex gap-2 items-center flex-wrap">
                    <div className="text-muted-alt">{datasetCountLabel}</div>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            to={datasetUrl('new')}
                            data-testid="create-dataset-button"
                            data-attr="create-dataset-button"
                            size="small"
                        >
                            New dataset
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </div>

            <LemonTable
                id="datasets"
                loading={datasetsLoading}
                columns={columns}
                dataSource={datasets.results}
                pagination={pagination}
                noSortingCancellation
                sorting={sorting}
                onSort={(newSorting) =>
                    setFilters({
                        order_by: newSorting
                            ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                            : undefined,
                    })
                }
                rowKey="id"
                loadingSkeletonRows={DATASETS_PER_PAGE}
                nouns={['dataset', 'datasets']}
            />
        </SceneContent>
    )
}
