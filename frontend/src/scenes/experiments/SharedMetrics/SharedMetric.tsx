import { useActions, useValues } from 'kea'

import { IconBalance, IconCheckCircle, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, Spinner } from '@posthog/lemon-ui'

import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { tagsModel } from '~/models/tagsModel'
import { ExperimentMetric, NodeKind } from '~/queries/schema/schema-general'
import { ExperimentsTabs } from '~/types'

import { ExperimentMetricForm } from '../ExperimentMetricForm'
import { getDefaultFunnelsMetric, getDefaultTrendsMetric } from '../utils'
import { LegacySharedFunnelsMetricForm } from './LegacySharedFunnelsMetricForm'
import { LegacySharedTrendsMetricForm } from './LegacySharedTrendsMetricForm'
import { SharedMetricLogicProps, sharedMetricLogic } from './sharedMetricLogic'

export const scene: SceneExport<SharedMetricLogicProps> = {
    component: SharedMetric,
    logic: sharedMetricLogic,
    paramsToProps: ({ params: { id, action } }) => ({
        sharedMetricId: id === 'new' ? null : parseInt(id),
        action: action || (id === 'new' ? 'create' : 'update'),
    }),
}

export function SharedMetric(): JSX.Element {
    const { sharedMetric, action } = useValues(sharedMetricLogic)
    const { setSharedMetric, createSharedMetric, updateSharedMetric, deleteSharedMetric } =
        useActions(sharedMetricLogic)

    const { currentTeam } = useValues(teamLogic)
    const { tags: allExistingTags } = useValues(tagsModel)

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

            <ScenePanel>
                <ScenePanelInfoSection>
                    <SceneTags
                        onSave={(tags) => {
                            setSharedMetric({
                                tags: tags,
                            })
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
                        <ButtonPrimitive
                            variant="danger"
                            menuItem
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Delete this metric?',
                                    content: (
                                        <div className="text-sm text-secondary">This action cannot be undone.</div>
                                    ),
                                    primaryButton: {
                                        children: 'Delete',
                                        type: 'primary',
                                        onClick: () => deleteSharedMetric(),
                                        size: 'small',
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                        type: 'tertiary',
                                        size: 'small',
                                    },
                                })
                            }}
                        >
                            <IconTrash /> Delete
                        </ButtonPrimitive>
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
                    <LemonButton
                        disabledReason={sharedMetric.name ? undefined : 'You must give your metric a name'}
                        size="small"
                        type="primary"
                        onClick={() => {
                            if (['create', 'duplicate'].includes(action)) {
                                createSharedMetric()
                                return
                            }

                            updateSharedMetric()
                        }}
                    >
                        Save
                    </LemonButton>
                }
            />
            <SceneDivider />

            {sharedMetric.query.kind === NodeKind.ExperimentMetric ? (
                <ExperimentMetricForm
                    metric={sharedMetric.query as ExperimentMetric}
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
            <div className="flex justify-between">
                {/* {action === 'update' && (
                    <LemonButton
                        size="medium"
                        type="primary"
                        status="danger"
                        onClick={() => {
                            LemonDialog.open({
                                title: 'Delete this metric?',
                                content: <div className="text-sm text-secondary">This action cannot be undone.</div>,
                                primaryButton: {
                                    children: 'Delete',
                                    type: 'primary',
                                    onClick: () => deleteSharedMetric(),
                                    size: 'small',
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                    type: 'tertiary',
                                    size: 'small',
                                },
                            })
                        }}
                    >
                        Delete
                    </LemonButton>
                )} */}
                <LemonButton
                    disabledReason={sharedMetric.name ? undefined : 'You must give your metric a name'}
                    size="medium"
                    type="primary"
                    onClick={() => {
                        if (['create', 'duplicate'].includes(action)) {
                            createSharedMetric()
                            return
                        }

                        updateSharedMetric()
                    }}
                >
                    Save
                </LemonButton>
            </div>
        </SceneContent>
    )
}
