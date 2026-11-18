import { IconInfo, IconPencil } from '@posthog/icons'
import { LemonBanner, LemonInput } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { SeriesActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import {
    NodeKind,
    isExperimentExposureNode,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentQuantileMetric,
    isExperimentRatioMetric,
    isExperimentRetentionMetric,
} from '~/queries/schema/schema-general'
import {
    ChartDisplayCategory,
    ExperimentMetricGoal,
    ExperimentMetricMathType,
    FunnelConversionWindowTimeUnit,
} from '~/types'

import { ExperimentMetricValueFormatSection } from 'products/experiments/frontend/components/ExperimentMetricValueFormatSection'
import { ExperimentQuantileMetricFields } from 'products/experiments/frontend/components/ExperimentQuantileMetricFields'
import { WarehouseNativeMetricFields } from 'products/experiments/frontend/warehouseNative/WarehouseNativeMetricFields'

import { ExperimentMetricConversionWindowFilter } from './ExperimentMetricConversionWindowFilter'
import {
    DATA_SOURCE_HELP,
    EXPOSURE_DOCS_URL,
    EXPOSURE_HELP,
    type ExperimentMetricFormProps,
    GOAL_HELP,
    HOGQL_DOCS_URL,
    HOGQL_HELP,
    POSTHOG_SOURCE_BLOCKED,
    RECENT_ACTIVITY_HEALTH_HELP,
    RECENT_ACTIVITY_HELP,
    RETENTION_COMPLETION_HELP,
    RETENTION_START_HELP,
    RETENTION_WINDOW_EXAMPLE,
    RETENTION_WINDOW_HELP,
    START_HANDLING_HELP,
    WAREHOUSE_SOURCE_BLOCKED,
    dataWarehousePopoverFields,
    exposureSharingHelp,
    retentionExposureStartHelp,
    getExposureCriteriaLabel,
    useExperimentMetricForm,
} from './experimentMetricFormModel'
import { ExperimentMetricFunnelOrderSelector } from './ExperimentMetricFunnelOrderSelector'
import {
    ExperimentMetricOutlierHandling,
    ExperimentRatioMetricOutlierHandling,
} from './ExperimentMetricOutlierHandling'
import { ExperimentMetricThreshold } from './ExperimentMetricThreshold'
import { EXPOSURE_DEFAULT_EVENT } from './exposureContract'
import { metricSourcesToSeries, seriesToMetricSource } from './metricQueryUtils'
import { commonActionFilterProps } from './Metrics/Selectors'
import { getExposureConfigDisplayName } from './utils'

export { getExposureCriteriaLabel } from './experimentMetricFormModel'

export function ExperimentMetricForm(props: ExperimentMetricFormProps): JSX.Element {
    const {
        metric,
        isSharedMetric = false,
        handleSetMetric,
        exposureCriteria,
        openExposureCriteriaModal,
        resolvedExposureEvent = EXPOSURE_DEFAULT_EVENT,
    } = props
    const {
        showDataSource,
        usesWarehouseNative,
        handleDataSourceChange,
        warehouseExposure,
        handleMetricTypeChange,
        radioOptions,
        activationConfig,
        handleSetSeries,
        mathAvailability,
        allowedMathTypes,
        hideDeleteBtn,
        setRetentionStartSource,
        isLoading,
        eventCount,
        getEventTypeLabel,
    } = useExperimentMetricForm(props)

    return (
        <SceneContent>
            {showDataSource && (
                <>
                    <SceneSection title="Data source" className="max-w-prose">
                        <div className="flex flex-col gap-2">
                            <div>
                                <LemonSegmentedButton
                                    size="small"
                                    value={usesWarehouseNative ? 'warehouse_native' : 'posthog'}
                                    onChange={handleDataSourceChange}
                                    options={[
                                        {
                                            value: 'posthog',
                                            label: 'PostHog data',
                                            disabledReason: warehouseExposure ? POSTHOG_SOURCE_BLOCKED : undefined,
                                            'data-attr': 'experiment-metric-data-source-posthog',
                                        },
                                        {
                                            value: 'warehouse_native',
                                            label: 'Warehouse-native',
                                            disabledReason:
                                                !isSharedMetric && !warehouseExposure
                                                    ? WAREHOUSE_SOURCE_BLOCKED
                                                    : undefined,
                                            'data-attr': 'experiment-metric-data-source-warehouse-native',
                                        },
                                    ]}
                                />
                            </div>
                            <div className="text-secondary text-xs">{DATA_SOURCE_HELP}</div>
                        </div>
                    </SceneSection>
                    <SceneDivider />
                </>
            )}
            <SceneSection title={isSharedMetric ? 'Shared metric type' : 'Metric type'} className="max-w-prose">
                <div>
                    <LemonRadio
                        data-attr="metrics-selector"
                        value={metric.metric_type}
                        onChange={handleMetricTypeChange}
                        options={radioOptions}
                    />
                </div>
            </SceneSection>
            <SceneDivider />
            <SceneSection title="Metric" className="max-w-prose">
                <LemonBanner
                    type="info"
                    action={
                        exposureCriteria && openExposureCriteriaModal
                            ? {
                                  size: 'xsmall',
                                  onClick: () => openExposureCriteriaModal(exposureCriteria),
                                  icon: <IconPencil />,
                                  tooltip: 'Edit exposure criteria',
                              }
                            : undefined
                    }
                >
                    <span className="inline-flex items-center gap-2 flex-wrap">
                        {exposureCriteria ? (
                            <>
                                Counts only after exposure event{' '}
                                <LemonTag>{getExposureCriteriaLabel(exposureCriteria, resolvedExposureEvent)}</LemonTag>
                                {activationConfig && (
                                    <>
                                        and activation event{' '}
                                        <LemonTag>{getExposureConfigDisplayName(activationConfig)}</LemonTag>
                                    </>
                                )}
                            </>
                        ) : usesWarehouseNative ? (
                            <>Counts only after exposure. Each experiment sets its own exposure query.</>
                        ) : (
                            <>
                                Counts only after exposure event (<LemonTag>{resolvedExposureEvent}</LemonTag> by
                                default)
                            </>
                        )}
                        <Tooltip
                            docLink={EXPOSURE_DOCS_URL}
                            title={
                                <div className="space-y-2">
                                    <p>{EXPOSURE_HELP}</p>
                                    <p>{exposureSharingHelp(!!exposureCriteria)}</p>
                                </div>
                            }
                        >
                            <IconInfo className="text-muted-alt text-base" />
                        </Tooltip>
                    </span>
                </LemonBanner>

                {isExperimentMeanMetric(metric) && (
                    <>
                        {usesWarehouseNative ? (
                            <WarehouseNativeMetricFields
                                metric={metric}
                                handleSetMetric={handleSetMetric}
                                exposureBinding={warehouseExposure}
                            />
                        ) : (
                            <SeriesActionFilter
                                bordered
                                series={metricSourcesToSeries([metric.source])}
                                trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
                                dataWarehouseNodeKind={NodeKind.ExperimentDataWarehouseNode}
                                onChange={handleSetSeries}
                                typeKey="experiment-metric"
                                buttonCopy="Add graph series"
                                showSeriesIndicator={false}
                                hideRename={true}
                                entitiesLimit={1}
                                showNumericalPropsOnly={true}
                                mathAvailability={mathAvailability}
                                allowedMathTypes={allowedMathTypes}
                                dataWarehousePopoverFields={dataWarehousePopoverFields}
                                {...commonActionFilterProps}
                            />
                        )}
                        {metric.source.math === ExperimentMetricMathType.HogQL && (
                            <div className="text-muted text-sm mt-2">
                                {HOGQL_HELP}{' '}
                                <Link to={HOGQL_DOCS_URL} target="_blank">
                                    Learn more about HogQL expressions
                                </Link>
                            </div>
                        )}
                        <ExperimentMetricThreshold
                            math={metric.source.math}
                            value={metric.threshold}
                            onChange={(value) =>
                                handleSetMetric({
                                    ...metric,
                                    threshold: value,
                                    /**
                                     * Setting a threshold disables outlier handling, so clear any stale
                                     * bounds to keep the metric consistent with the UI and pass validation.
                                     */
                                    ...(value !== undefined && {
                                        lower_bound_percentile: undefined,
                                        upper_bound_percentile: undefined,
                                        ignore_zeros: undefined,
                                    }),
                                })
                            }
                        />
                    </>
                )}

                {isExperimentQuantileMetric(metric) && (
                    <ExperimentQuantileMetricFields metric={metric} handleSetMetric={handleSetMetric} />
                )}

                {isExperimentFunnelMetric(metric) && (
                    <SeriesActionFilter
                        bordered
                        series={metricSourcesToSeries(metric.series)}
                        trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
                        dataWarehouseNodeKind={NodeKind.ExperimentDataWarehouseNode}
                        onChange={handleSetSeries}
                        typeKey="experiment-metric"
                        buttonCopy="Add step"
                        showSeriesIndicator={false}
                        hideRename={false}
                        hideDeleteBtn={hideDeleteBtn}
                        sortable={true}
                        showNestedArrow={true}
                        // showNumericalPropsOnly={true}
                        mathAvailability={mathAvailability}
                        allowedMathTypes={allowedMathTypes}
                        {...commonActionFilterProps}
                        dataWarehousePopoverFields={dataWarehousePopoverFields}
                    />
                )}

                {isExperimentRatioMetric(metric) && usesWarehouseNative && (
                    <WarehouseNativeMetricFields
                        metric={metric}
                        handleSetMetric={handleSetMetric}
                        exposureBinding={warehouseExposure}
                    />
                )}

                {isExperimentRatioMetric(metric) && !usesWarehouseNative && (
                    <div className="space-y-4">
                        <div>
                            <LemonLabel className="mb-1">Numerator (what you're measuring)</LemonLabel>
                            <SeriesActionFilter
                                bordered
                                series={metricSourcesToSeries([metric.numerator])}
                                trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
                                dataWarehouseNodeKind={NodeKind.ExperimentDataWarehouseNode}
                                onChange={(series) => {
                                    const source = seriesToMetricSource(series)
                                    if (source) {
                                        handleSetMetric({
                                            ...metric,
                                            numerator: source,
                                        })
                                    }
                                }}
                                typeKey="experiment-metric-numerator"
                                buttonCopy="Add numerator event"
                                showSeriesIndicator={false}
                                hideRename={true}
                                entitiesLimit={1}
                                showNumericalPropsOnly={true}
                                mathAvailability={mathAvailability}
                                allowedMathTypes={allowedMathTypes}
                                dataWarehousePopoverFields={dataWarehousePopoverFields}
                                {...commonActionFilterProps}
                            />
                        </div>
                        <div>
                            <LemonLabel className="mb-1">Denominator (what you're dividing by)</LemonLabel>
                            <SeriesActionFilter
                                bordered
                                series={metricSourcesToSeries([metric.denominator])}
                                trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
                                dataWarehouseNodeKind={NodeKind.ExperimentDataWarehouseNode}
                                onChange={(series) => {
                                    const source = seriesToMetricSource(series)
                                    if (source) {
                                        handleSetMetric({
                                            ...metric,
                                            denominator: source,
                                        })
                                    }
                                }}
                                typeKey="experiment-metric-denominator"
                                buttonCopy="Add denominator event"
                                showSeriesIndicator={false}
                                hideRename={true}
                                entitiesLimit={1}
                                mathAvailability={mathAvailability}
                                allowedMathTypes={allowedMathTypes}
                                dataWarehousePopoverFields={dataWarehousePopoverFields}
                                {...commonActionFilterProps}
                            />
                        </div>
                    </div>
                )}

                {isExperimentRetentionMetric(metric) && (
                    <div className="space-y-4">
                        <div>
                            <LemonLabel className="mb-1">
                                Start event
                                <Tooltip title={RETENTION_START_HELP}>
                                    <IconInfo className="ml-1 text-muted" />
                                </Tooltip>
                            </LemonLabel>
                            <LemonRadio
                                className="my-1.5"
                                data-attr="experiment-retention-start-source"
                                orientation="horizontal"
                                value={isExperimentExposureNode(metric.start_event) ? 'exposure' : 'custom'}
                                onChange={setRetentionStartSource}
                                options={[
                                    { value: 'custom', label: 'Custom event' },
                                    { value: 'exposure', label: 'Experiment exposure' },
                                ]}
                            />
                            {isExperimentExposureNode(metric.start_event) ? (
                                <div className="text-muted text-xs">{retentionExposureStartHelp(isSharedMetric)}</div>
                            ) : (
                                <SeriesActionFilter
                                    bordered
                                    series={metricSourcesToSeries([metric.start_event])}
                                    trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
                                    dataWarehouseNodeKind={NodeKind.ExperimentDataWarehouseNode}
                                    onChange={(series) => {
                                        const source = seriesToMetricSource(series)
                                        if (source) {
                                            handleSetMetric({ ...metric, start_event: source })
                                        }
                                    }}
                                    typeKey="experiment-metric-start-event"
                                    buttonCopy="Add start event"
                                    showSeriesIndicator={false}
                                    hideRename={true}
                                    entitiesLimit={1}
                                    showNumericalPropsOnly={true}
                                    mathAvailability={mathAvailability}
                                    allowedMathTypes={allowedMathTypes}
                                    dataWarehousePopoverFields={dataWarehousePopoverFields}
                                    {...commonActionFilterProps}
                                />
                            )}
                        </div>

                        <div>
                            <LemonLabel className="mb-1">
                                Completion event
                                <Tooltip title={RETENTION_COMPLETION_HELP}>
                                    <IconInfo className="ml-1 text-muted" />
                                </Tooltip>
                            </LemonLabel>
                            <SeriesActionFilter
                                bordered
                                series={metricSourcesToSeries([metric.completion_event])}
                                trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
                                dataWarehouseNodeKind={NodeKind.ExperimentDataWarehouseNode}
                                onChange={(series) => {
                                    const source = seriesToMetricSource(series)
                                    if (source) {
                                        handleSetMetric({ ...metric, completion_event: source })
                                    }
                                }}
                                typeKey="experiment-metric-completion-event"
                                buttonCopy="Add completion event"
                                showSeriesIndicator={false}
                                hideRename={true}
                                entitiesLimit={1}
                                showNumericalPropsOnly={true}
                                mathAvailability={mathAvailability}
                                allowedMathTypes={allowedMathTypes}
                                dataWarehousePopoverFields={dataWarehousePopoverFields}
                                {...commonActionFilterProps}
                            />
                        </div>

                        <div>
                            <LemonLabel className="mb-1">
                                Retention window
                                <Tooltip
                                    title={
                                        <div className="space-y-2">
                                            <p>{RETENTION_WINDOW_HELP}</p>
                                            <p>{RETENTION_WINDOW_EXAMPLE}</p>
                                        </div>
                                    }
                                >
                                    <IconInfo className="ml-1 text-muted" />
                                </Tooltip>
                            </LemonLabel>
                            <div className="flex items-center gap-2">
                                <span className="text-muted">From</span>
                                <LemonInput
                                    type="number"
                                    min={0}
                                    value={metric.retention_window_start}
                                    onChange={(value) => {
                                        handleSetMetric({
                                            ...metric,
                                            retention_window_start: Number(value),
                                        })
                                    }}
                                    className="w-20"
                                />
                                <span className="text-muted">to</span>
                                <LemonInput
                                    type="number"
                                    min={metric.retention_window_start || 0}
                                    value={metric.retention_window_end}
                                    onChange={(value) => {
                                        handleSetMetric({
                                            ...metric,
                                            retention_window_end: Number(value),
                                        })
                                    }}
                                    className="w-20"
                                />
                                <LemonSelect
                                    value={metric.retention_window_unit || 'day'}
                                    onChange={(value) => {
                                        handleSetMetric({
                                            ...metric,
                                            retention_window_unit: value as FunnelConversionWindowTimeUnit,
                                        })
                                    }}
                                    options={[
                                        { label: 'days', value: FunnelConversionWindowTimeUnit.Day },
                                        { label: 'hours', value: FunnelConversionWindowTimeUnit.Hour },
                                    ]}
                                />
                            </div>
                            <span className="text-muted text-xs">
                                {isExperimentExposureNode(metric.start_event)
                                    ? "After the user's first exposure"
                                    : 'After the start event'}
                            </span>
                        </div>

                        {!isExperimentExposureNode(metric.start_event) && (
                            <div>
                                <LemonLabel className="mb-1">
                                    When users have multiple start events
                                    <Tooltip title={START_HANDLING_HELP}>
                                        <IconInfo className="ml-1 text-muted" />
                                    </Tooltip>
                                </LemonLabel>
                                <LemonSelect
                                    value={metric.start_handling || 'first_seen'}
                                    onChange={(value) => {
                                        handleSetMetric({
                                            ...metric,
                                            start_handling: value as 'first_seen' | 'last_seen',
                                        })
                                    }}
                                    options={[
                                        {
                                            label: 'Use first start event',
                                            value: 'first_seen',
                                        },
                                        {
                                            label: 'Use last start event',
                                            value: 'last_seen',
                                        },
                                    ]}
                                />
                            </div>
                        )}
                    </div>
                )}
            </SceneSection>
            <SceneDivider />
            <SceneSection title="Goal" className="max-w-prose">
                <div className="flex flex-col gap-1">
                    <LemonSelect<ExperimentMetricGoal>
                        value={metric.goal || ExperimentMetricGoal.Increase}
                        onChange={(value) => handleSetMetric({ ...metric, goal: value })}
                        options={[
                            { value: ExperimentMetricGoal.Increase, label: 'Increase' },
                            { value: ExperimentMetricGoal.Decrease, label: 'Decrease' },
                        ]}
                    />
                    <div className="text-muted text-xs mt-1">{GOAL_HELP}</div>
                </div>
            </SceneSection>
            <SceneDivider />
            <ExperimentMetricValueFormatSection metric={metric} handleSetMetric={handleSetMetric} />
            {/* The backend ignores the conversion window for exposure-anchored retention: the retention window already anchors on exposure */}
            {!(isExperimentRetentionMetric(metric) && isExperimentExposureNode(metric.start_event)) && (
                <>
                    <ExperimentMetricConversionWindowFilter metric={metric} handleSetMetric={handleSetMetric} />
                    <SceneDivider />
                </>
            )}
            {isExperimentFunnelMetric(metric) && (
                <>
                    <ExperimentMetricFunnelOrderSelector metric={metric} handleSetMetric={handleSetMetric} />
                    <SceneDivider />
                </>
            )}
            {isExperimentMeanMetric(metric) && (
                <>
                    <ExperimentMetricOutlierHandling metric={metric} handleSetMetric={handleSetMetric} />
                    {!usesWarehouseNative && <SceneDivider />}
                </>
            )}
            {isExperimentRatioMetric(metric) && (
                <>
                    <ExperimentRatioMetricOutlierHandling metric={metric} handleSetMetric={handleSetMetric} />
                    {!usesWarehouseNative && <SceneDivider />}
                </>
            )}
            {!usesWarehouseNative && (
                <SceneSection
                    title="Recent activity"
                    className="max-w-prose"
                    titleHelper={
                        <div className="flex flex-col gap-2">
                            <div>{RECENT_ACTIVITY_HELP}</div>
                            <div>{RECENT_ACTIVITY_HEALTH_HELP}</div>
                            <div>
                                If you see zero activity, double-check that this metric is being tracked properly in
                                your application. Head to{' '}
                                <Link target="_blank" className="font-semibold" to={urls.insightNew()}>
                                    Product analytics
                                    <IconOpenInNew fontSize="18" />
                                </Link>{' '}
                                to do a detailed analysis of the events received so far.
                            </div>
                        </div>
                    }
                >
                    <div className="border rounded p-4 bg-bg-light">
                        {isLoading ? (
                            <div className="flex items-center gap-2">
                                <Spinner />
                                <span className="text-muted">Loading recent activity...</span>
                            </div>
                        ) : (
                            <div className="flex flex-col gap-1">
                                <div className="text-2xl font-semibold">
                                    {eventCount !== null ? eventCount.toLocaleString() : '0'}
                                </div>
                                <div className="text-sm text-muted">
                                    {eventCount !== null && eventCount > 0
                                        ? `${getEventTypeLabel()} in the past 2 weeks`
                                        : 'No recent activity'}
                                </div>
                            </div>
                        )}
                    </div>
                </SceneSection>
            )}
        </SceneContent>
    )
}
