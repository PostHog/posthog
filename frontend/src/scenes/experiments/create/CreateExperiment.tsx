import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useState } from 'react'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import type { Experiment } from '~/types'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ExposureCriteriaPanel } from './ExposureCriteriaPanel'
import { ExposureCriteriaPanelHeader } from './ExposureCriteriaPanelHeader'
import { MetricsPanel, MetricsPanelHeader } from './MetricsPanel'
import { VariantsPanel } from './VariantsPanel'
import { VariantsPanelHeader } from './VariantsPanelHeader'
import { createExperimentLogic } from './createExperimentLogic'

const LemonFieldError = ({ error }: { error: string }): JSX.Element => {
    return (
        <div className="text-danger flex items-center gap-1 text-sm">
            <IconErrorOutline className="text-xl shrink-0" /> {error}
        </div>
    )
}

type CreateExperimentProps = Partial<{
    draftExperiment: Experiment
}>

export const CreateExperiment = ({ draftExperiment }: CreateExperimentProps): JSX.Element => {
    const { HogfettiComponent } = useHogfetti({ count: 100, duration: 3000 })

    const { experiment, experimentErrors, sharedMetrics, isExperimentSubmitting } = useValues(
        createExperimentLogic({ experiment: draftExperiment })
    )
    const { setExperimentValue, setExperiment, setSharedMetrics, setExposureCriteria, setFeatureFlagConfig } =
        useActions(createExperimentLogic({ experiment: draftExperiment }))

    const [selectedPanel, setSelectedPanel] = useState<string | null>(null)

    return (
        <div className="flex flex-col xl:grid xl:grid-cols-[1fr_400px] gap-x-4 h-full">
            <Form logic={createExperimentLogic} formKey="experiment" enableFormOnSubmit>
                <HogfettiComponent />
                <SceneContent className="max-w-none flex-1">
                    <SceneTitleSection
                        name={experiment.name}
                        description={null}
                        resourceType={{
                            type: 'experiment',
                        }}
                        canEdit={userHasAccess(
                            AccessControlResourceType.Experiment,
                            AccessControlLevel.Editor,
                            experiment.user_access_level
                        )}
                        forceEdit
                        onNameChange={(name) => setExperimentValue('name', name)}
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
                                        data-attr="save-experiment"
                                        type="primary"
                                        size="small"
                                        htmlType="submit"
                                    >
                                        Save as draft
                                    </LemonButton>
                                </AccessControlAction>
                            </>
                        }
                    />
                    {experimentErrors.name && typeof experimentErrors.name === 'string' && (
                        <LemonFieldError error={experimentErrors.name} />
                    )}
                    <SceneDivider />
                    <SceneSection title="Hypothesis" description="Describe your experiment in a few sentences.">
                        <LemonField name="description">
                            <LemonTextArea
                                placeholder="The goal of this experiment is ..."
                                data-attr="experiment-hypothesis"
                                value={experiment.description}
                                onChange={(value) => {
                                    setExperimentValue('description', value)
                                }}
                            />
                        </LemonField>
                    </SceneSection>
                    <SceneDivider />
                    <LemonCollapse
                        activeKey={selectedPanel ?? undefined}
                        defaultActiveKey="experiment-exposure"
                        onChange={setSelectedPanel}
                        className="bg-surface-primary"
                        panels={[
                            {
                                key: 'experiment-exposure',
                                header: <ExposureCriteriaPanelHeader experiment={experiment} />,
                                content: (
                                    <ExposureCriteriaPanel
                                        experiment={experiment}
                                        onChange={setExposureCriteria}
                                        onNext={() => setSelectedPanel('experiment-variants')}
                                    />
                                ),
                            },
                            {
                                key: 'experiment-variants',
                                header: <VariantsPanelHeader experiment={experiment} />,
                                content: (
                                    <VariantsPanel
                                        experiment={experiment}
                                        updateFeatureFlag={setFeatureFlagConfig}
                                        onPrevious={() => setSelectedPanel('experiment-exposure')}
                                        onNext={() => setSelectedPanel('experiment-metrics')}
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
                                                    saved_metrics: (experiment.saved_metrics ?? []).filter(
                                                        (savedMetric) =>
                                                            savedMetric.saved_metric !== metric.sharedMetricId
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
            </Form>
        </div>
    )
}
