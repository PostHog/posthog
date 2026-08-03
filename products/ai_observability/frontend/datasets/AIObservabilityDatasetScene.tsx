import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { combineUrl, router } from 'kea-router'
import { useEffect } from 'react'

import { IconArchive, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonTab, LemonTabs, Link, ProfilePicture } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
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
import { userHasAccess } from 'lib/utils/accessControlUtils'
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
import { DatasetLogicProps, DatasetTab, isDataset, aiObservabilityDatasetLogic } from './aiObservabilityDatasetLogic'
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
    } = useValues(aiObservabilityDatasetLogic)
    const {
        submitDatasetForm,
        loadDataset,
        editDataset,
        archiveDataset,
        setDatasetFormValue,
        triggerDatasetItemModal,
        onUnmount,
    } = useActions(aiObservabilityDatasetLogic)
    const { searchParams } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]

    const displayEditForm = isNewDataset || isEditingDataset

    // TRICKY: Scene logic is not unmounted. Workaround.
    useEffect(() => {
        return () => onUnmount()
    }, [onUnmount])

    if (isDatasetMissing) {
        return <NotFound object="dataset" />
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
                <SceneTitleSection
                    name={datasetForm.name}
                    resourceType={{ type: 'llm_analytics' }}
                    isLoading={datasetLoading}
                    actions={
                        <>
                            {!shouldDisplaySkeleton ? (
                                displayEditForm ? (
                                    <>
                                        <LemonButton
                                            type="secondary"
                                            data-attr="cancel-dataset"
                                            onClick={() => {
                                                if (isEditingDataset) {
                                                    editDataset(false)
                                                    loadDataset()
                                                } else {
                                                    router.actions.push(
                                                        combineUrl(urls.aiObservabilityDatasets(), searchParams).url
                                                    )
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
                                ) : (
                                    <>
                                        <AccessControlAction
                                            resourceType={AccessControlResourceType.LlmAnalytics}
                                            minAccessLevel={AccessControlLevel.Editor}
                                        >
                                            <LemonButton
                                                type="secondary"
                                                onClick={() => editDataset(true)}
                                                loading={false}
                                                data-attr="edit-dataset"
                                                size="small"
                                            >
                                                Edit
                                            </LemonButton>
                                        </AccessControlAction>
                                        <AccessControlAction
                                            resourceType={AccessControlResourceType.LlmAnalytics}
                                            minAccessLevel={AccessControlLevel.Editor}
                                        >
                                            <LemonButton
                                                type="primary"
                                                onClick={() => triggerDatasetItemModal(true)}
                                                data-attr="add-dataset-item"
                                                icon={<IconPlusSmall />}
                                                size="small"
                                            >
                                                Add item
                                            </LemonButton>
                                        </AccessControlAction>
                                    </>
                                )
                            ) : undefined}
                        </>
                    }
                />

                {isDataset(dataset) && sceneMenuBarEnabled && (
                    <SceneMenuBar>
                        <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                            <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />
                            <SceneMenuBarSeparator />
                            <AccessControlAction
                                resourceType={AccessControlResourceType.LlmAnalytics}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                {({ disabledReason }) => (
                                    <SceneMenuBarItem
                                        variant="destructive"
                                        disabled={!!disabledReason || datasetLoading || isArchivingDataset}
                                        onClick={() => {
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
                                        }}
                                        data-attr={`${RESOURCE_TYPE}-menubar-archive`}
                                    >
                                        <IconArchive />
                                        Archive
                                    </SceneMenuBarItem>
                                )}
                            </AccessControlAction>
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
                                canEdit={userHasAccess(
                                    AccessControlResourceType.LlmAnalytics,
                                    AccessControlLevel.Editor
                                )}
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
                                canEdit={userHasAccess(
                                    AccessControlResourceType.LlmAnalytics,
                                    AccessControlLevel.Editor
                                )}
                            />
                        </ScenePanelInfoSection>
                        <ScenePanelDivider />
                        <ScenePanelActionsSection>
                            <ScenePanelDivider />
                            <AccessControlAction
                                resourceType={AccessControlResourceType.LlmAnalytics}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <ButtonPrimitive
                                    onClick={() => {
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
                                    }}
                                    variant="danger"
                                    menuItem
                                    data-attr={`${RESOURCE_TYPE}-archive`}
                                    disabledReasons={{
                                        'Dataset is loading': datasetLoading,
                                        'Dataset is being archived': isArchivingDataset,
                                    }}
                                >
                                    <IconArchive />
                                    Archive
                                </ButtonPrimitive>
                            </AccessControlAction>
                        </ScenePanelActionsSection>
                    </ScenePanel>
                )}

                {displayEditForm ? <EditDatasetForm /> : isDataset(dataset) ? <DatasetTabs dataset={dataset} /> : null}
            </SceneContent>
        </Form>
    )
}

function DatasetTabs({ dataset }: { dataset: Dataset }): JSX.Element {
    const { activeTab, isDatasetItemModalOpen, selectedDatasetItem } = useValues(aiObservabilityDatasetLogic)
    const { closeModalAndRefetchDatasetItems } = useActions(aiObservabilityDatasetLogic)
    const { searchParams } = useValues(router)

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
            <div>
                <p className="m-0">{dataset.description || <span className="italic">Description (optional)</span>}</p>
            </div>

            <LemonTabs activeKey={activeTab} data-attr="dataset-tabs" tabs={tabs} />

            <DatasetItemModal
                isOpen={isDatasetItemModalOpen}
                onClose={closeModalAndRefetchDatasetItems}
                partialDatasetItem={selectedDatasetItem}
                datasetId={dataset.id}
                displayBulkCreationButton
            />
        </>
    )
}

function DatasetItems({ dataset }: { dataset: Dataset }): JSX.Element {
    const { archivingDatasetItemId, datasetItems, datasetItemsLoading, pagination } =
        useValues(aiObservabilityDatasetLogic)
    const { archiveDatasetItem, loadDatasetItems } = useActions(aiObservabilityDatasetLogic)
    const { searchParams } = useValues(router)

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
                    return <span>—</span>
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
                                    Edit
                                </LemonButton>

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.LlmAnalytics}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        status="danger"
                                        onClick={() => archiveDatasetItem(item.id, item.version)}
                                        loading={archivingDatasetItemId === item.id}
                                        disabledReason={
                                            archivingDatasetItemId && archivingDatasetItemId !== item.id
                                                ? 'Another dataset item is being archived'
                                                : undefined
                                        }
                                        data-attr={`dataset-item-${item.id}-dropdown-archive`}
                                        fullWidth
                                    >
                                        Archive
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
        <>
            <div className="flex justify-between items-center">
                <RefreshButton
                    onClick={() => {
                        loadDatasetItems(true)
                    }}
                    isRefreshing={datasetItemsLoading}
                />
            </div>

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
