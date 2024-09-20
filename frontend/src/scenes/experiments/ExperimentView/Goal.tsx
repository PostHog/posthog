import '../Experiment.scss'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonModal, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'

import { ActionFilter as ActionFilterType, AnyPropertyFilter, Experiment, FilterType, InsightType } from '~/types'

import { EXPERIMENT_EXPOSURE_INSIGHT_ID, EXPERIMENT_INSIGHT_ID } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { MetricSelector } from '../MetricSelector'

export function MetricDisplay({ filters }: { filters?: FilterType }): JSX.Element {
    const experimentInsightType = filters?.insight || InsightType.TRENDS

    return (
        <>
            {([...(filters?.events || []), ...(filters?.actions || [])] as ActionFilterType[])
                .sort((a, b) => (a.order || 0) - (b.order || 0))
                .map((event: ActionFilterType, idx: number) => (
                    <div key={idx} className="mb-2">
                        <div className="flex mb-1">
                            <div
                                className="shrink-0 w-6 h-6 mr-2 font-bold text-center text-primary-alt border rounded"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ backgroundColor: 'var(--bg-table)' }}
                            >
                                {experimentInsightType === InsightType.FUNNELS ? (event.order || 0) + 1 : idx + 1}
                            </div>
                            <b>
                                <InsightLabel
                                    action={event}
                                    showCountedByTag={experimentInsightType === InsightType.TRENDS}
                                    hideIcon
                                    showEventName
                                />
                            </b>
                        </div>
                        <div className="space-y-1">
                            {event.properties?.map((prop: AnyPropertyFilter) => (
                                <PropertyFilterButton key={prop.key} item={prop} />
                            ))}
                        </div>
                    </div>
                ))}
        </>
    )
}

export function ExposureMetric({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment } = useValues(experimentLogic({ experimentId }))
    const { openExperimentExposureModal, updateExperimentExposure } = useActions(experimentLogic({ experimentId }))

    return (
        <>
            <div className="card-secondary mb-2 mt-2">
                Exposure metric
                <Tooltip
                    title={`This metric determines how we calculate exposure for the experiment. Only users who have this event alongside the property '$feature/${experiment.feature_flag_key}' are included in the exposure calculations.`}
                >
                    <IconInfo className="ml-1 text-muted text-sm" />
                </Tooltip>
            </div>
            {experiment.parameters?.custom_exposure_filter ? (
                <MetricDisplay filters={experiment.parameters.custom_exposure_filter} />
            ) : (
                <span className="description">Default via $feature_flag_called events</span>
            )}
            <div className="mb-2 mt-2">
                <span className="flex">
                    <LemonButton type="secondary" size="xsmall" onClick={openExperimentExposureModal} className="mr-2">
                        Change exposure metric
                    </LemonButton>
                    {experiment.parameters?.custom_exposure_filter && (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            size="xsmall"
                            onClick={() => updateExperimentExposure(null)}
                        >
                            Reset
                        </LemonButton>
                    )}
                </span>
            </div>
        </>
    )
}

export function ExperimentGoalModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment, isExperimentGoalModalOpen, experimentLoading, goalInsightDataLoading } = useValues(
        experimentLogic({ experimentId })
    )
    const { closeExperimentGoalModal, updateExperimentGoal, setNewExperimentInsight } = useActions(
        experimentLogic({ experimentId })
    )

    return (
        <LemonModal
            isOpen={isExperimentGoalModalOpen}
            onClose={closeExperimentGoalModal}
            width={1000}
            title="Change experiment goal"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton form="edit-experiment-goal-form" type="secondary" onClick={closeExperimentGoalModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        disabledReason={
                            goalInsightDataLoading && 'The insight needs to be loaded before saving the goal'
                        }
                        form="edit-experiment-goal-form"
                        onClick={() => {
                            updateExperimentGoal(experiment.filters)
                        }}
                        type="primary"
                        loading={experimentLoading}
                        data-attr="create-annotation-submit"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <Form
                logic={experimentLogic}
                props={{ experimentId }}
                formKey="experiment"
                id="edit-experiment-goal-form"
                className="space-y-4"
            >
                <Field name="filters">
                    <MetricSelector
                        dashboardItemId={EXPERIMENT_INSIGHT_ID}
                        setPreviewInsight={setNewExperimentInsight}
                        showDateRangeBanner
                    />
                </Field>
            </Form>
        </LemonModal>
    )
}

export function ExperimentExposureModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment, isExperimentExposureModalOpen, experimentLoading } = useValues(
        experimentLogic({ experimentId })
    )
    const { closeExperimentExposureModal, updateExperimentExposure, setExperimentExposureInsight } = useActions(
        experimentLogic({ experimentId })
    )

    return (
        <LemonModal
            isOpen={isExperimentExposureModalOpen}
            onClose={closeExperimentExposureModal}
            width={1000}
            title="Change experiment exposure"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        type="secondary"
                        onClick={closeExperimentExposureModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        onClick={() => {
                            if (experiment.parameters.custom_exposure_filter) {
                                updateExperimentExposure(experiment.parameters.custom_exposure_filter)
                            }
                        }}
                        type="primary"
                        loading={experimentLoading}
                        data-attr="create-annotation-submit"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <Form
                logic={experimentLogic}
                props={{ experimentId }}
                formKey="experiment"
                id="edit-experiment-exposure-form"
                className="space-y-4"
            >
                <Field name="filters">
                    <MetricSelector
                        dashboardItemId={EXPERIMENT_EXPOSURE_INSIGHT_ID}
                        setPreviewInsight={setExperimentExposureInsight}
                        forceTrendExposureMetric
                    />
                </Field>
            </Form>
        </LemonModal>
    )
}

export function Goal(): JSX.Element {
    const { experiment, experimentId, experimentInsightType, experimentMathAggregationForTrends } =
        useValues(experimentLogic)
    const { openExperimentGoalModal } = useActions(experimentLogic({ experimentId }))

    return (
        <div>
            <div>
                <div className="inline-flex space-x-2">
                    <h2 className="font-semibold text-lg mb-0">Experiment goal</h2>
                    <Tooltip
                        title={
                            <>
                                {' '}
                                This <b>{experimentInsightType === InsightType.FUNNELS ? 'funnel' : 'trend'}</b>{' '}
                                {experimentInsightType === InsightType.FUNNELS
                                    ? 'experiment measures conversion at each stage.'
                                    : 'experiment tracks the count of a single metric.'}
                            </>
                        }
                    >
                        <IconInfo className="text-muted-alt text-base" />
                    </Tooltip>
                </div>
            </div>
            <div className="inline-flex space-x-6">
                <div>
                    <div className="card-secondary mb-2 mt-2">
                        {experimentInsightType === InsightType.FUNNELS ? 'Conversion goal steps' : 'Trend goal'}
                    </div>
                    <MetricDisplay filters={experiment.filters} />
                    <LemonButton size="xsmall" type="secondary" onClick={openExperimentGoalModal}>
                        Change goal
                    </LemonButton>
                </div>
                {experimentInsightType === InsightType.TRENDS &&
                    !experimentMathAggregationForTrends(experiment.filters) && (
                        <>
                            <LemonDivider className="" vertical />
                            <div className="">
                                <div className="mt-auto ml-auto">
                                    <ExposureMetric experimentId={experimentId} />
                                </div>
                            </div>
                        </>
                    )}
            </div>
        </div>
    )
}
