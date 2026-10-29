import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconArchive, IconArrowLeft, IconDownload, IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { toAccessControlLevel } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'

import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'
import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneTextarea } from '~/lib/components/Scenes/SceneTextarea'
import { SceneTextInput } from '~/lib/components/Scenes/SceneTextInput'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { OfflineEvaluationsScene } from '../offline-evaluations/OfflineEvaluationsScene'
import { OfflineEvaluationsTabs } from '../offline-evaluations/OfflineEvaluationsTabs'
import { DatasetLogicProps, DatasetTab, isDataset, aiObservabilityDatasetLogic } from './aiObservabilityDatasetLogic'
import { getDatasetListUrl } from './aiObservabilityDatasetsLogic'
import { DatasetContents } from './DatasetContents'
import { EditDatasetForm } from './EditDatasetForm'

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
        datasetExportDisabledReason,
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
        setActiveTab,
    } = useActions(aiObservabilityDatasetLogic)
    const { searchParams } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const cancelEditing = (): void => {
        if (isEditingDataset) {
            editDataset(false)
            loadDataset()
        } else {
            router.actions.push(getDatasetListUrl(searchParams))
        }
    }

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
        return (
            <OfflineEvaluationsScene>
                <NotFound object="dataset" />
            </OfflineEvaluationsScene>
        )
    }

    if (datasetLoadError?.status === 403) {
        return (
            <OfflineEvaluationsScene>
                <AccessDenied object="dataset" />
            </OfflineEvaluationsScene>
        )
    }

    if (datasetLoadError && !isDataset(dataset)) {
        return (
            <OfflineEvaluationsScene>
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadDataset }}>
                    {datasetLoadError.detail || "Couldn't load this dataset. Try again."}
                </LemonBanner>
            </OfflineEvaluationsScene>
        )
    }

    if (shouldDisplaySkeleton) {
        return (
            <OfflineEvaluationsScene>
                <div className="flex flex-col gap-2">
                    <LemonSkeleton active className="h-4 w-2/5" />
                    <LemonSkeleton active className="h-4 w-full" />
                    <LemonSkeleton active className="h-4 w-full" />
                    <LemonSkeleton active className="h-4 w-3/5" />
                </div>
            </OfflineEvaluationsScene>
        )
    }

    return (
        <Form id="dataset-form" formKey="datasetForm" logic={aiObservabilityDatasetLogic}>
            <OfflineEvaluationsScene>
                {datasetLoadError && (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadDataset }}>
                        {datasetLoadError.detail || "Couldn't refresh this dataset. Try again."}
                    </LemonBanner>
                )}
                {isDataset(dataset) && sceneMenuBarEnabled && (
                    <SceneMenuBar>
                        <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                            <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />
                            <SceneMenuBarSeparator />
                            <SceneMenuBarItem
                                disabled={datasetExportLoading || !!datasetExportDisabledReason}
                                tooltip={datasetExportDisabledReason}
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

                <div className="flex flex-wrap items-center gap-3">
                    <OfflineEvaluationsTabs activeTab="datasets" />
                    <div className="flex flex-1 basis-80 flex-wrap items-center gap-2">
                        <nav aria-label="Dataset" className="flex min-w-0 flex-1 basis-40 items-center gap-2">
                            <LemonButton
                                size="small"
                                icon={<IconArrowLeft />}
                                aria-label="Back to datasets"
                                tooltip="Back to datasets"
                                data-attr="back-to-datasets"
                                to={getDatasetListUrl(searchParams)}
                            />
                            <h2 className="text-base font-semibold m-0 truncate" title={datasetForm.name}>
                                {isNewDataset ? 'New dataset' : (isDataset(dataset) && dataset.name) || 'Dataset'}
                            </h2>
                            {isDataset(dataset) && dataset.archived && (
                                <LemonTag type="muted" size="small">
                                    Archived
                                </LemonTag>
                            )}
                        </nav>
                        <div className="flex flex-wrap items-center gap-2">
                            {!displayEditForm && isDataset(dataset) ? (
                                <>
                                    <LemonButton
                                        size="small"
                                        onClick={() => setActiveTab(DatasetTab.Metadata)}
                                        data-attr="dataset-details"
                                        icon={<IconInfo />}
                                    >
                                        Details
                                    </LemonButton>
                                    {canEditDataset && (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={() => editDataset(true)}
                                            data-attr="edit-dataset"
                                        >
                                            Edit
                                        </LemonButton>
                                    )}
                                </>
                            ) : null}
                        </div>
                    </div>
                </div>
                {!displayEditForm && isDataset(dataset) && dataset.description && (
                    <p className="text-muted m-0">{dataset.description}</p>
                )}
                {displayEditForm ? (
                    <div className="flex max-w-160 flex-col gap-4">
                        <EditDatasetForm />
                        <div className="flex flex-wrap items-center gap-2">
                            {todayRailNav ? (
                                <>
                                    <Button
                                        variant="outline"
                                        data-attr="cancel-dataset"
                                        onClick={cancelEditing}
                                        disabledReason={isDatasetFormSubmitting ? 'Saving…' : undefined}
                                    >
                                        Cancel
                                    </Button>
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.LlmAnalytics}
                                        minAccessLevel={AccessControlLevel.Editor}
                                        userAccessLevel={
                                            isDataset(dataset)
                                                ? toAccessControlLevel(dataset.user_access_level)
                                                : undefined
                                        }
                                    >
                                        <Button
                                            variant="primary"
                                            data-attr="save-dataset"
                                            onClick={submitDatasetForm}
                                            loading={isDatasetFormSubmitting}
                                        >
                                            {isNewDataset ? 'Create dataset' : 'Save'}
                                        </Button>
                                    </AccessControlAction>
                                </>
                            ) : (
                                <>
                                    <LemonButton
                                        type="secondary"
                                        data-attr="cancel-dataset"
                                        onClick={cancelEditing}
                                        disabledReason={isDatasetFormSubmitting ? 'Saving…' : undefined}
                                        size="small"
                                    >
                                        Cancel
                                    </LemonButton>
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.LlmAnalytics}
                                        minAccessLevel={AccessControlLevel.Editor}
                                        userAccessLevel={
                                            isDataset(dataset)
                                                ? toAccessControlLevel(dataset.user_access_level)
                                                : undefined
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
                            )}
                        </div>
                    </div>
                ) : isDataset(dataset) ? (
                    <DatasetContents dataset={dataset} />
                ) : null}
            </OfflineEvaluationsScene>
        </Form>
    )
}
