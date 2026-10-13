import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconBalance, IconCheckCircle, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, Link, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
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
import { tagsModel } from '~/models/tagsModel'
import { ExperimentMetric, NodeKind } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, ExperimentsTabs } from '~/types'

import type { ExperimentSavedMetricLinkedExperimentApi } from 'products/experiments/frontend/generated/api.schemas'
import { LegacySharedFunnelsMetricForm } from 'products/experiments/frontend/legacy/sharedMetrics/LegacySharedFunnelsMetricForm'
import { LegacySharedTrendsMetricForm } from 'products/experiments/frontend/legacy/sharedMetrics/LegacySharedTrendsMetricForm'

import { ExperimentMetricForm } from '../ExperimentMetricForm'
import { getDefaultFunnelsMetric, getDefaultTrendsMetric } from '../utils'
import { openDeleteSharedMetricDialog } from './deleteSharedMetricDialog'
import { SharedMetricLinkedExperiments } from './SharedMetricLinkedExperiments'
import { SharedMetricLogicProps, sharedMetricLogic } from './sharedMetricLogic'

export const scene: SceneExport<SharedMetricLogicProps> = {
    component: SharedMetric,
    logic: sharedMetricLogic,
    paramsToProps: ({ params: { id, action } }) => ({
        sharedMetricId: id === 'new' ? null : parseInt(id),
        action: action || (id === 'new' ? 'create' : 'update'),
    }),
}

function openSaveWithRunningExperimentsDialog(
    runningExperiments: readonly ExperimentSavedMetricLinkedExperimentApi[],
    onSave: () => void
): void {
    LemonDialog.open({
        title: 'Save changes to this metric?',
        content: (
            <div className="text-sm text-secondary max-w-120">
                <p>
                    This metric is used by{' '}
                    {runningExperiments.length === 1
                        ? 'a running experiment'
                        : `${runningExperiments.length} running experiments`}
                    . Saving changes to the metric definition also changes{' '}
                    {runningExperiments.length === 1 ? 'its' : 'their'} results.
                </p>
                <ul className="list-disc pl-4 space-y-1 max-h-60 overflow-y-auto">
                    {runningExperiments.map((experiment) => (
                        <li key={experiment.id} className="truncate">
                            <Link to={urls.experiment(experiment.id)}>{experiment.name}</Link>
                        </li>
                    ))}
                </ul>
            </div>
        ),
        primaryButton: {
            children: 'Save',
            type: 'primary',
            onClick: onSave,
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

export function SharedMetric(): JSX.Element {
    const { sharedMetric, action, metricSaving } = useValues(sharedMetricLogic)
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    const { setSharedMetric, createSharedMetric, updateSharedMetric, deleteSharedMetric } =
        useActions(sharedMetricLogic)

    const { currentTeam, currentProjectId } = useValues(teamLogic)
    const { tags: allExistingTags } = useValues(tagsModel)
    const [deleteCheckLoading, setDeleteCheckLoading] = useState(false)

    const runningExperiments = (sharedMetric?.linked_experiments || []).filter((experiment) => experiment.is_running)

    const handleDelete = async (): Promise<void> => {
        if (!sharedMetric.id || deleteCheckLoading) {
            return
        }
        setDeleteCheckLoading(true)
        try {
            await openDeleteSharedMetricDialog({
                projectId: currentProjectId,
                sharedMetricId: sharedMetric.id,
                onDelete: deleteSharedMetric,
            })
        } finally {
            setDeleteCheckLoading(false)
        }
    }

    const handleSave = (): void => {
        if (metricSaving) {
            return
        }
        if (['create', 'duplicate'].includes(action)) {
            createSharedMetric()
            return
        }
        if (runningExperiments.length > 0) {
            openSaveWithRunningExperimentsDialog(runningExperiments, () => updateSharedMetric())
            return
        }
        updateSharedMetric()
    }

    if (!sharedMetric || !sharedMetric.query) {
        return (
            <div className="fixed inset-0 flex justify-center items-center">
                <Spinner className="text-5xl" />
            </div>
        )
    }

    return (
        <SceneContent>
            {sharedMetric.query.kind !== NodeKind.ExperimentMetric && (
                <div className="flex gap-4 mb-4">
                    <div
                        className={`flex-1 cursor-pointer p-4 rounded border ${
                            sharedMetric.query.kind === NodeKind.ExperimentTrendsQuery
                                ? 'border-accent bg-accent-highlight-secondary'
                                : 'border-primary'
                        }`}
                        onClick={() => {
                            setSharedMetric({
                                query: getDefaultTrendsMetric(),
                            })
                        }}
                    >
                        <div className="font-semibold flex justify-between items-center">
                            <span>Trend</span>
                            {sharedMetric.query.kind === NodeKind.ExperimentTrendsQuery && (
                                <IconCheckCircle fontSize={18} color="var(--color-accent)" />
                            )}
                        </div>
                        <div className="text-secondary text-sm leading-relaxed">
                            Track a single event, action or a property value.
                        </div>
                    </div>
                    <div
                        className={`flex-1 cursor-pointer p-4 rounded border ${
                            sharedMetric.query.kind === NodeKind.ExperimentFunnelsQuery
                                ? 'border-accent bg-accent-highlight-secondary'
                                : 'border-primary'
                        }`}
                        onClick={() => {
                            setSharedMetric({
                                query: getDefaultFunnelsMetric(),
                            })
                        }}
                    >
                        <div className="font-semibold flex justify-between items-center">
                            <span>Funnel</span>
                            {sharedMetric.query.kind === NodeKind.ExperimentFunnelsQuery && (
                                <IconCheckCircle fontSize={18} color="var(--color-accent)" />
                            )}
                        </div>
                        <div className="text-secondary text-sm leading-relaxed">
                            Analyze conversion rates between sequential steps.
                        </div>
                    </div>
                </div>
            )}

            {sceneMenuBarEnabled && action === 'update' && (
                <SceneMenuBar>
                    <SceneMenuBarMenu label="File" dataAttr="shared-metric-menubar-file">
                        <SceneMenuBarFileItems dataAttrKey="shared-metric" />
                        <SceneMenuBarSeparator />
                        <AccessControlAction
                            resourceType={AccessControlResourceType.ExperimentSavedMetric}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={sharedMetric.user_access_level}
                        >
                            {({ disabledReason }) => (
                                <SceneMenuBarItem
                                    variant="destructive"
                                    opensFloatingUi
                                    disabled={!!disabledReason || deleteCheckLoading}
                                    onClick={() => void handleDelete()}
                                    data-attr="shared-metric-menubar-delete"
                                >
                                    <IconTrash />
                                    Delete
                                </SceneMenuBarItem>
                            )}
                        </AccessControlAction>
                    </SceneMenuBarMenu>
                </SceneMenuBar>
            )}
            <ScenePanel>
                <ScenePanelInfoSection>
                    <SceneTags
                        onSave={(tags) => {
                            setSharedMetric({
                                tags: tags,
                            })
                            if (action === 'update') {
                                updateSharedMetric(false)
                            }
                        }}
                        canEdit
                        tags={sharedMetric.tags}
                        tagsAvailable={allExistingTags}
                        dataAttrKey="shared-metric"
                    />
                </ScenePanelInfoSection>
                <ScenePanelDivider />
                <ScenePanelActionsSection>
                    {action === 'update' && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.ExperimentSavedMetric}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={sharedMetric.user_access_level}
                        >
                            <ButtonPrimitive
                                variant="danger"
                                menuItem
                                disabled={deleteCheckLoading}
                                onClick={() => void handleDelete()}
                            >
                                <IconTrash /> Delete
                            </ButtonPrimitive>
                        </AccessControlAction>
                    )}
                </ScenePanelActionsSection>
            </ScenePanel>

            <SceneTitleSection
                name={sharedMetric.name}
                resourceType={{ type: 'experiment', forceIcon: <IconBalance /> }}
                description={sharedMetric.description}
                onNameChange={(newName) => {
                    setSharedMetric({
                        name: newName,
                    })
                }}
                onDescriptionChange={(newDescription) => {
                    setSharedMetric({
                        description: newDescription,
                    })
                }}
                canEdit
                forceEdit={!sharedMetric.id}
                forceBackTo={{
                    name: 'Experiments / shared metrics',
                    path: `${urls.experiments()}?tab=${ExperimentsTabs.SharedMetrics}`,
                    key: ExperimentsTabs.SharedMetrics,
                }}
                actions={
                    <>
                        {action === 'update' && (
                            <More
                                overlay={
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.ExperimentSavedMetric}
                                        minAccessLevel={AccessControlLevel.Editor}
                                        userAccessLevel={sharedMetric.user_access_level}
                                    >
                                        <LemonButton
                                            fullWidth
                                            size="small"
                                            icon={<IconTrash />}
                                            status="danger"
                                            data-attr="shared-metric-delete"
                                            loading={deleteCheckLoading}
                                            onClick={() => void handleDelete()}
                                        >
                                            Delete
                                        </LemonButton>
                                    </AccessControlAction>
                                }
                            />
                        )}
                        <AccessControlAction
                            resourceType={AccessControlResourceType.ExperimentSavedMetric}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={sharedMetric.user_access_level}
                        >
                            <LemonButton
                                disabledReason={sharedMetric.name ? undefined : 'You must give your metric a name'}
                                loading={metricSaving}
                                size="small"
                                type="primary"
                                onClick={handleSave}
                            >
                                Save
                            </LemonButton>
                        </AccessControlAction>
                    </>
                }
            />

            <div className="flex flex-col gap-4 @min-[64rem]/main-content:flex-row @min-[64rem]/main-content:items-start">
                <div className="min-w-0 flex-1 order-2 @min-[64rem]/main-content:order-1">
                    {sharedMetric.query.kind === NodeKind.ExperimentMetric ? (
                        <ExperimentMetricForm
                            metric={sharedMetric.query as ExperimentMetric}
                            isSharedMetric={true}
                            handleSetMetric={(newMetric) => {
                                setSharedMetric({
                                    ...sharedMetric,
                                    query: newMetric,
                                })
                            }}
                            filterTestAccounts={currentTeam?.test_account_filters?.length ? true : false}
                        />
                    ) : sharedMetric.query.kind === NodeKind.ExperimentTrendsQuery ? (
                        <LegacySharedTrendsMetricForm />
                    ) : (
                        <LegacySharedFunnelsMetricForm />
                    )}
                </div>
                {action === 'update' && (sharedMetric.linked_experiments || []).length > 0 && (
                    <div className="order-1 @min-[64rem]/main-content:order-2 @min-[64rem]/main-content:w-80 shrink-0 @min-[64rem]/main-content:sticky @min-[64rem]/main-content:top-4">
                        <SharedMetricLinkedExperiments experiments={sharedMetric.linked_experiments || []} />
                    </div>
                )}
            </div>
            <div className="flex justify-between">
                <AccessControlAction
                    resourceType={AccessControlResourceType.ExperimentSavedMetric}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={sharedMetric.user_access_level}
                >
                    <LemonButton
                        disabledReason={sharedMetric.name ? undefined : 'You must give your metric a name'}
                        loading={metricSaving}
                        size="medium"
                        type="primary"
                        onClick={handleSave}
                    >
                        Save
                    </LemonButton>
                </AccessControlAction>
            </div>
        </SceneContent>
    )
}
