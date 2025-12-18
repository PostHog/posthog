import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import type { Experiment } from '~/types'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { experimentSceneLogic } from '../experimentSceneLogic'
import { ExperimentDetailsPanel } from './ExperimentDetailsPanel'
import { ExperimentDetailsPanelHeader } from './ExperimentDetailsPanelHeader'
import { ExposureCriteriaPanel } from './ExposureCriteriaPanel'
import { ExposureCriteriaPanelHeader } from './ExposureCriteriaPanelHeader'
import { MetricsPanel, MetricsPanelHeader } from './MetricsPanel'
import { VariantsPanel } from './VariantsPanel'
import { VariantsPanelHeader } from './VariantsPanelHeader'
import { createExperimentLogic } from './createExperimentLogic'

interface ExperimentFormProps {
    draftExperiment?: Experiment
    tabId?: string
}

export const ExperimentForm = ({ draftExperiment, tabId }: ExperimentFormProps): JSX.Element => {
    const logic = createExperimentLogic({ experiment: draftExperiment, tabId })
    useAttachedLogic(logic, tabId ? experimentSceneLogic({ tabId }) : undefined)

    const { experiment, experimentErrors, canSubmitExperiment, sharedMetrics, isExperimentSubmitting, isEditMode } =
        useValues(logic)
    const {
        setExperimentValue,
        setExperiment,
        setSharedMetrics,
        setExposureCriteria,
        setFeatureFlagConfig,
        saveExperiment,
        validateField,
    } = useActions(logic)

    const [selectedPanel, setSelectedPanel] = useState<string | null>(null)

    const title = isEditMode ? 'Edit experiment' : 'New experiment'

    return (
        <div>
            <SceneContent>
                <SceneTitleSection
                    name={title}
                    description={null}
                    resourceType={{
                        type: 'experiment',
                    }}
                    canEdit={false}
                    actions={
                        <>
                            <LemonButton
                                data-attr="cancel-experiment"
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    router.actions.push(urls.experiments())
                                }}
                            >
                                Cancel
                            </LemonButton>
                            <AccessControlAction
                                resourceType={AccessControlResourceType.Experiment}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={experiment.user_access_level}
                            >
                                <LemonButton
                                    loading={isExperimentSubmitting}
                                    disabledReason={!canSubmitExperiment ? 'Experiment is not valid' : undefined}
                                    data-attr="save-experiment"
                                    type="primary"
                                    size="small"
                                    onClick={saveExperiment}
                                >
                                    Save as draft
                                </LemonButton>
                            </AccessControlAction>
                        </>
                    }
                />
                <LemonCollapse
                    activeKey={selectedPanel ?? undefined}
                    defaultActiveKey="experiment-details"
                    onChange={setSelectedPanel}
                    className="bg-surface-primary"
                    panels={[
                        {
                            key: 'experiment-details',
                            header: <ExperimentDetailsPanelHeader experiment={experiment} />,
                            content: (
                                <ExperimentDetailsPanel
                                    experiment={experiment}
                                    experimentErrors={experimentErrors}
                                    onChange={setExperimentValue}
                                    onValidate={validateField}
                                    onNext={() => setSelectedPanel('experiment-exposure')}
                                />
                            ),
                        },
                        {
                            key: 'experiment-exposure',
                            header: <ExposureCriteriaPanelHeader experiment={experiment} />,
                            content: (
                                <ExposureCriteriaPanel
                                    experiment={experiment}
                                    onChange={setExposureCriteria}
                                    onPrevious={() => setSelectedPanel('experiment-details')}
                                    onNext={() => setSelectedPanel('experiment-variants')}
                                />
                            ),
                        },
                        {
                            key: 'experiment-variants',
                            header: <VariantsPanelHeader experiment={experiment} disabled={isEditMode} />,
                            content: (
                                <VariantsPanel
                                    experiment={experiment}
                                    updateFeatureFlag={setFeatureFlagConfig}
                                    onPrevious={() => setSelectedPanel('experiment-exposure')}
                                    onNext={() => setSelectedPanel('experiment-metrics')}
                                    disabled={isEditMode}
                                />
                            ),
                        },
                        {
                            key: 'experiment-metrics',
                            header: <MetricsPanelHeader experiment={experiment} sharedMetrics={sharedMetrics} />,
                            content: (
                                <MetricsPanel
                                    experiment={experiment}
                                    sharedMetrics={sharedMetrics}
                                    onSaveMetric={(metric, context) => {
                                        const isNew = !experiment[context.field].some((m) => m.uuid === metric.uuid)

                                        setExperiment({
                                            ...experiment,
                                            [context.field]: isNew
                                                ? [...experiment[context.field], metric]
                                                : experiment[context.field].map((m) =>
                                                      m.uuid === metric.uuid ? metric : m
                                                  ),
                                            ...(isNew && {
                                                [context.orderingField]: [
                                                    ...(experiment[context.orderingField] ?? []),
                                                    metric.uuid,
                                                ],
                                            }),
                                        })
                                    }}
                                    onDeleteMetric={(metric, context) => {
                                        if (metric.isSharedMetric) {
                                            setExperiment({
                                                ...experiment,
                                                [context.orderingField]: (
                                                    experiment[context.orderingField] ?? []
                                                ).filter((uuid) => uuid !== metric.uuid),
                                                // Remove from saved_metrics so modal shows it as available again
                                                saved_metrics: (experiment.saved_metrics ?? []).filter(
                                                    (sm) => sm.saved_metric !== metric.sharedMetricId
                                                ),
                                            })
                                            setSharedMetrics({
                                                ...sharedMetrics,
                                                [context.type]: sharedMetrics[context.type].filter(
                                                    (m) => m.uuid !== metric.uuid
                                                ),
                                            })
                                            return
                                        }

                                        const metricIndex = experiment[context.field].findIndex(
                                            ({ uuid }) => uuid === metric.uuid
                                        )

                                        if (metricIndex !== -1) {
                                            setExperiment({
                                                ...experiment,
                                                [context.field]: experiment[context.field].filter(
                                                    ({ uuid }) => uuid !== metric.uuid
                                                ),
                                                [context.orderingField]: (
                                                    experiment[context.orderingField] ?? []
                                                ).filter((uuid) => uuid !== metric.uuid),
                                            })
                                        }
                                    }}
                                    onSaveSharedMetrics={(metrics, context) => {
                                        setExperiment({
                                            ...experiment,
                                            [context.orderingField]: [
                                                ...(experiment[context.orderingField] ?? []),
                                                ...metrics.map((metric) => metric.uuid),
                                            ],
                                            saved_metrics: [
                                                ...(experiment.saved_metrics ?? []),
                                                ...metrics.map((metric) => ({
                                                    saved_metric: metric.sharedMetricId,
                                                })),
                                            ],
                                        })
                                        setSharedMetrics({
                                            ...sharedMetrics,
                                            [context.type]: [...sharedMetrics[context.type], ...metrics],
                                        })
                                    }}
                                    onPrevious={() => setSelectedPanel('experiment-variants')}
                                />
                            ),
                        },
                    ]}
                />
            </SceneContent>
        </div>
    )
}
