import { Col, InputNumber, Row, Slider, Tooltip } from 'antd'
import { useValues, useActions } from 'kea'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { dayjs } from 'lib/dayjs'
import {
    ActionFilter as ActionFilterType,
    AnyPropertyFilter,
    FilterType,
    InsightType,
    MultivariateFlagVariant,
} from '~/types'
import { experimentLogic } from './experimentLogic'
import { ExperimentWorkflow } from './ExperimentWorkflow'
import { humanFriendlyNumber } from 'lib/utils'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { Field, Form } from 'kea-forms'
import { MetricSelector } from './MetricSelector'
import { IconInfo } from 'lib/lemon-ui/icons'
import { TZLabel } from 'lib/components/TZLabel'
import { EXPERIMENT_EXPOSURE_INSIGHT_ID, EXPERIMENT_INSIGHT_ID } from './constants'
import { groupFilters } from 'scenes/feature-flags/FeatureFlags'
import { urls } from 'scenes/urls'

interface ExperimentPreviewProps {
    experimentId: number | 'new'
    trendCount: number
    trendExposure?: number
    funnelSampleSize?: number
    funnelConversionRate: number
    funnelEntrants?: number
}

export function ExperimentPreview({
    experimentId,
    trendCount,
    funnelConversionRate,
    trendExposure,
    funnelSampleSize,
    funnelEntrants,
}: ExperimentPreviewProps): JSX.Element {
    const {
        experimentInsightType,
        editingExistingExperiment,
        minimumDetectableChange,
        expectedRunningTime,
        aggregationLabel,
        experiment,
        isExperimentGoalModalOpen,
        isExperimentExposureModalOpen,
        experimentLoading,
        experimentMathAggregationForTrends,
    } = useValues(experimentLogic({ experimentId }))
    const {
        setExperiment,
        openExperimentGoalModal,
        closeExperimentGoalModal,
        updateExperimentGoal,
        openExperimentExposureModal,
        closeExperimentExposureModal,
        updateExperimentExposure,
        setNewExperimentInsight,
        setExperimentExposureInsight,
    } = useActions(experimentLogic({ experimentId }))
    const sliderMaxValue =
        experimentInsightType === InsightType.FUNNELS
            ? 100 - funnelConversionRate < 50
                ? 100 - funnelConversionRate
                : 50
            : 50

    const currentDuration = dayjs().diff(dayjs(experiment?.start_date), 'hour')

    let runningTime = 0
    if (experiment?.start_date) {
        runningTime = expectedRunningTime(funnelEntrants || 1, funnelSampleSize || 0, currentDuration)
    } else {
        runningTime = expectedRunningTime(funnelEntrants || 1, funnelSampleSize || 0)
    }

    const expectedEndDate = dayjs(experiment?.start_date).add(runningTime, 'hour')
    const showEndDate = !experiment?.end_date && currentDuration >= 24 && funnelEntrants && funnelSampleSize

    const targetingProperties = experiment.feature_flag?.filters

    return (
        <Row>
            <Col span={!experiment?.start_date && experimentId !== 'new' && !editingExistingExperiment ? 12 : 24}>
                {experimentId === 'new' && (
                    <Row className="experiment-preview-row">
                        <div>
                            <div>
                                <b>Experiment preview</b>
                            </div>
                            <div className="text-muted">
                                Here are the baseline metrics for your experiment. Adjust your minimum detectible
                                threshold to adjust for the smallest conversion value you'll accept, and the experiment
                                duration.{' '}
                            </div>
                        </div>
                    </Row>
                )}
                {(experimentId === 'new' || editingExistingExperiment) && (
                    <Row className="mb-4">
                        <Col span={24}>
                            <div>
                                <b>Minimum acceptable improvement</b>
                                <Tooltip
                                    title={
                                        'Minimum acceptable improvement is a calculation that estimates the smallest significant improvement you are willing to accept.'
                                    }
                                >
                                    <IconInfo className="ml-1 text-muted text-xl" />
                                </Tooltip>
                            </div>
                            <Row className="mde-slider">
                                <Col span={8}>
                                    <Slider
                                        defaultValue={5}
                                        value={minimumDetectableChange}
                                        min={1}
                                        max={sliderMaxValue}
                                        trackStyle={{ background: 'var(--primary)' }}
                                        handleStyle={{ background: 'var(--primary)' }}
                                        onChange={(value) => {
                                            setExperiment({
                                                parameters: {
                                                    ...experiment.parameters,
                                                    minimum_detectable_effect: value,
                                                },
                                            })
                                        }}
                                        tipFormatter={(value) => `${value}%`}
                                    />
                                </Col>
                                <InputNumber
                                    min={1}
                                    max={sliderMaxValue}
                                    defaultValue={5}
                                    formatter={(value) => `${value}%`}
                                    style={{ margin: '0 16px' }}
                                    value={minimumDetectableChange}
                                    onChange={(value) => {
                                        setExperiment({
                                            parameters: {
                                                ...experiment.parameters,
                                                minimum_detectable_effect: value ?? undefined,
                                            },
                                        })
                                    }}
                                />
                            </Row>
                        </Col>
                    </Row>
                )}
                <Row className={`experiment-preview-row ${experiment?.start_date ? 'mr' : ''}`}>
                    {experimentInsightType === InsightType.TRENDS ? (
                        <>
                            {!experiment?.start_date && (
                                <>
                                    <Col span={6}>
                                        <div className="card-secondary">Baseline Count</div>
                                        <div className="l4">{humanFriendlyNumber(trendCount || 0)}</div>
                                    </Col>
                                    <Col span={6}>
                                        <div className="card-secondary">Minimum Acceptable Count</div>
                                        <div className="l4">
                                            {humanFriendlyNumber(
                                                trendCount + Math.ceil(trendCount * (minimumDetectableChange / 100)) ||
                                                    0
                                            )}
                                        </div>
                                    </Col>
                                </>
                            )}
                            <Col span={12}>
                                <div className="card-secondary">Recommended running time</div>
                                <div>
                                    <span className="l4">~{humanFriendlyNumber(trendExposure || 0)}</span> days
                                </div>
                            </Col>
                        </>
                    ) : (
                        <>
                            {!experiment?.start_date && (
                                <>
                                    <Col span={12}>
                                        <div className="card-secondary">Baseline Conversion Rate</div>
                                        <div className="l4">{funnelConversionRate.toFixed(1)}%</div>
                                    </Col>
                                    <Col span={12}>
                                        <div className="card-secondary">Minimum Acceptable Conversion Rate</div>
                                        <div className="l4">
                                            {(funnelConversionRate + minimumDetectableChange).toFixed(1)}%
                                        </div>
                                    </Col>
                                </>
                            )}
                            <Col span={12}>
                                <div className="card-secondary">Recommended Sample Size</div>
                                <div className="pb-4">
                                    <span className="l4">~{humanFriendlyNumber(funnelSampleSize || 0)}</span> persons
                                </div>
                            </Col>
                            {!experiment?.start_date && (
                                <Col span={12}>
                                    <div className="card-secondary">Recommended running time</div>
                                    <div>
                                        <span className="l4">~{humanFriendlyNumber(runningTime || 0)}</span> days
                                    </div>
                                </Col>
                            )}
                        </>
                    )}
                    <Row className="w-full mt-4">
                        <Col span={12}>
                            <div className="card-secondary">Experiment variants</div>
                            <ul className="variants-list">
                                {experiment?.parameters?.feature_flag_variants?.map(
                                    (variant: MultivariateFlagVariant, idx: number) => (
                                        <li key={idx}>{variant.key}</li>
                                    )
                                )}
                            </ul>
                        </Col>
                        <Col span={12}>
                            <div className="card-secondary">Participants</div>
                            <div style={{ display: 'inline-block' }}>
                                {targetingProperties ? (
                                    <>
                                        {groupFilters(targetingProperties, undefined, aggregationLabel)}
                                        <LemonButton
                                            to={
                                                experiment.feature_flag
                                                    ? urls.featureFlag(experiment.feature_flag.id)
                                                    : undefined
                                            }
                                            size="small"
                                            className="mt-0.5"
                                            type="secondary"
                                            center
                                        >
                                            Check flag release conditions
                                        </LemonButton>
                                    </>
                                ) : (
                                    '100% of all users'
                                )}
                            </div>
                        </Col>
                    </Row>
                    <Row className="w-full">
                        {experimentId !== 'new' && !editingExistingExperiment && (
                            <Col span={12}>
                                <div className="card-secondary mt-4">Start date</div>
                                {experiment?.start_date ? (
                                    <TZLabel time={experiment?.start_date} />
                                ) : (
                                    <span className="description">Not started yet</span>
                                )}
                            </Col>
                        )}
                        {experimentInsightType === InsightType.FUNNELS && showEndDate ? (
                            <Col span={12}>
                                <div className="card-secondary mt-4">Expected end date</div>
                                <span>
                                    {expectedEndDate.isAfter(dayjs())
                                        ? expectedEndDate.format('D MMM YYYY')
                                        : dayjs().format('D MMM YYYY')}
                                </span>
                            </Col>
                        ) : null}
                        {/* The null prevents showing a 0 while loading */}
                        {experiment?.end_date && (
                            <Col span={12}>
                                <div className="card-secondary mt-4">Completed date</div>
                                <TZLabel time={experiment?.end_date} />
                            </Col>
                        )}
                    </Row>
                </Row>
                {experimentId !== 'new' && !editingExistingExperiment && (
                    <Row className="experiment-preview-row">
                        <Col>
                            <div className="card-secondary mb-2">
                                {experimentInsightType === InsightType.FUNNELS ? 'Conversion goal steps' : 'Trend goal'}
                            </div>
                            <MetricDisplay filters={experiment.filters} />
                            {experiment?.start_date && (
                                <>
                                    <div className="mb-2 mt-4">
                                        <LemonButton type="secondary" onClick={openExperimentGoalModal}>
                                            Change experiment goal
                                        </LemonButton>
                                    </div>
                                    {experimentInsightType === InsightType.TRENDS &&
                                        !experimentMathAggregationForTrends && (
                                            <>
                                                <div className="card-secondary mb-2 mt-4">
                                                    Exposure metric
                                                    <Tooltip
                                                        title={`This metric determines how we calculate exposure for the experiment. Only users who have this event alongside the property '$feature/${experiment.feature_flag_key}' are included in exposure calculations.`}
                                                    >
                                                        <IconInfo className="ml-1 text-muted text-sm" />
                                                    </Tooltip>
                                                </div>
                                                {experiment.parameters?.custom_exposure_filter ? (
                                                    <MetricDisplay
                                                        filters={experiment.parameters.custom_exposure_filter}
                                                    />
                                                ) : (
                                                    <span className="description">
                                                        Default via $feature_flag_called events
                                                    </span>
                                                )}
                                                <div className="mb-2 mt-2">
                                                    <span className="flex">
                                                        <LemonButton
                                                            type="secondary"
                                                            size="small"
                                                            onClick={openExperimentExposureModal}
                                                            className="mr-2"
                                                        >
                                                            Change exposure metric
                                                        </LemonButton>
                                                        {experiment.parameters?.custom_exposure_filter && (
                                                            <LemonButton
                                                                type="secondary"
                                                                size="small"
                                                                status="danger"
                                                                className="mr-2"
                                                                onClick={() => updateExperimentExposure(null)}
                                                            >
                                                                Reset exposure
                                                            </LemonButton>
                                                        )}
                                                    </span>
                                                </div>
                                            </>
                                        )}
                                </>
                            )}
                        </Col>
                    </Row>
                )}
            </Col>

            {experimentId !== 'new' && !editingExistingExperiment && !experiment?.start_date && (
                <Col span={12} className="pl-4">
                    <ExperimentWorkflow />
                </Col>
            )}
            <LemonModal
                isOpen={isExperimentGoalModalOpen}
                onClose={closeExperimentGoalModal}
                width={1000}
                title={'Change experiment goal'}
                footer={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            form="edit-experiment-goal-form"
                            type="secondary"
                            onClick={closeExperimentGoalModal}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
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
            <LemonModal
                isOpen={isExperimentExposureModalOpen}
                onClose={closeExperimentExposureModal}
                width={1000}
                title={'Change experiment exposure'}
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
                        />
                    </Field>
                </Form>
            </LemonModal>
        </Row>
    )
}

export function MetricDisplay({ filters }: { filters?: FilterType }): JSX.Element {
    const experimentInsightType = filters?.insight || InsightType.TRENDS

    return (
        <>
            {([...(filters?.events || []), ...(filters?.actions || [])] as ActionFilterType[])
                .sort((a, b) => (a.order || 0) - (b.order || 0))
                .map((event: ActionFilterType, idx: number) => (
                    <Col key={idx} className="mb-2">
                        <Row style={{ marginBottom: 4 }}>
                            <div className="preview-conversion-goal-num">
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
                        </Row>
                        {event.properties?.map((prop: AnyPropertyFilter) => (
                            <PropertyFilterButton key={prop.key} item={prop} />
                        ))}
                    </Col>
                ))}
        </>
    )
}
