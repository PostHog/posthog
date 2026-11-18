import { IconInfo, IconPencil } from '@posthog/icons'
import {
    Badge,
    Button,
    Field,
    FieldContent,
    FieldDescription,
    FieldGroup,
    FieldLabel,
    FieldLegend,
    FieldSet,
    Heading,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    Label,
    RadioGroup,
    RadioGroupItem,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
    Spinner,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SeriesActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { urls } from 'scenes/urls'

import {
    ExperimentMetricType,
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

import { WarehouseNativeMetricFields } from 'products/experiments/frontend/warehouseNative/WarehouseNativeMetricFields'

import {
    DATA_SOURCE_HELP,
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
    getExposureCriteriaLabel,
    retentionExposureStartHelp,
    useExperimentMetricForm,
} from './experimentMetricFormModel'
import { QuillHelpTooltip } from './ExperimentView/QuillCardParts'
import { EXPOSURE_DEFAULT_EVENT } from './exposureContract'
import { metricSourcesToSeries, seriesToMetricSource } from './metricQueryUtils'
import { commonActionFilterProps } from './Metrics/Selectors'
import {
    QuillConversionWindowSection,
    QuillFormSection as Section,
    QuillFunnelOrderSection,
    QuillMetricThreshold,
    QuillOutlierHandlingSection,
    QuillQuantileMetricFields,
    QuillRatioOutlierHandlingSection,
    QuillValueFormatSection,
} from './QuillMetricFormSections'
import { getExposureConfigDisplayName } from './utils'

function LabelWithHelp({
    htmlFor,
    label,
    help,
}: {
    htmlFor?: string
    label: string
    help: React.ReactNode
}): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            <FieldLabel htmlFor={htmlFor}>{label}</FieldLabel>
            <QuillHelpTooltip label={label} help={help} />
        </span>
    )
}

const RETENTION_UNIT_OPTIONS = [
    { label: 'days', value: FunnelConversionWindowTimeUnit.Day },
    { label: 'hours', value: FunnelConversionWindowTimeUnit.Hour },
]
const START_HANDLING_OPTIONS = [
    { label: 'Use first start event', value: 'first_seen' },
    { label: 'Use last start event', value: 'last_seen' },
]
const GOAL_OPTIONS = [
    { value: ExperimentMetricGoal.Increase, label: 'Increase' },
    { value: ExperimentMetricGoal.Decrease, label: 'Decrease' },
]

function QuillSelect<T extends string>({
    value,
    options,
    onChange,
    className,
    dataAttr,
}: {
    value: T
    options: { value: T; label: string }[]
    onChange: (value: T) => void
    className?: string
    dataAttr?: string
}): JSX.Element {
    return (
        <Select value={value} onValueChange={(next) => next && onChange(next as T)}>
            <SelectTrigger className={className} data-attr={dataAttr}>
                <SelectValue>
                    {(current: string) => options.find((option) => option.value === current)?.label ?? current}
                </SelectValue>
            </SelectTrigger>
            <SelectContent>
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}

export function QuillExperimentMetricForm(props: ExperimentMetricFormProps): JSX.Element {
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

    const seriesProps = {
        bordered: true,
        trendsDisplayCategory: ChartDisplayCategory.TimeSeries,
        dataWarehouseNodeKind: NodeKind.ExperimentDataWarehouseNode as const,
        showSeriesIndicator: false,
        mathAvailability,
        allowedMathTypes,
        dataWarehousePopoverFields,
        ...commonActionFilterProps,
    }

    return (
        <div className="flex flex-col gap-4" data-attr="experiment-metric-form">
            {showDataSource && (
                <>
                    <Section title="Data source">
                        <ToggleGroup
                            variant="outline"
                            value={[usesWarehouseNative ? 'warehouse_native' : 'posthog']}
                            onValueChange={(next: string[]) =>
                                next[0] && handleDataSourceChange(next[0] as 'posthog' | 'warehouse_native')
                            }
                        >
                            <ToggleGroupItem
                                value="posthog"
                                disabledReason={warehouseExposure ? POSTHOG_SOURCE_BLOCKED : undefined}
                                data-attr="experiment-metric-data-source-posthog"
                            >
                                PostHog data
                            </ToggleGroupItem>
                            <ToggleGroupItem
                                value="warehouse_native"
                                disabledReason={
                                    !isSharedMetric && !warehouseExposure ? WAREHOUSE_SOURCE_BLOCKED : undefined
                                }
                                data-attr="experiment-metric-data-source-warehouse-native"
                            >
                                Warehouse-native
                            </ToggleGroupItem>
                        </ToggleGroup>
                        <Text size="xs" variant="muted">
                            {DATA_SOURCE_HELP}
                        </Text>
                    </Section>
                    <Separator />
                </>
            )}

            <Section title={isSharedMetric ? 'Shared metric type' : 'Metric type'}>
                <RadioGroup
                    value={metric.metric_type}
                    onValueChange={(value) => handleMetricTypeChange(value as ExperimentMetricType)}
                    data-attr="metrics-selector"
                >
                    {radioOptions.map((option) => (
                        <Field key={option.value} orientation="horizontal" className="items-start">
                            <RadioGroupItem
                                value={option.value}
                                id={`metric-type-${option.value}`}
                                disabled={!!option.disabledReason}
                                data-attr={option['data-attr']}
                            />
                            <FieldContent>
                                <Label htmlFor={`metric-type-${option.value}`}>{option.label}</Label>
                                <FieldDescription>{option.description}</FieldDescription>
                                {option.disabledReason && <FieldDescription>{option.disabledReason}</FieldDescription>}
                            </FieldContent>
                        </Field>
                    ))}
                </RadioGroup>
            </Section>
            <Separator />

            <Section title="Metric">
                <Item variant="outline" size="sm" tone="info">
                    <ItemMedia variant="icon" aria-hidden>
                        <IconInfo />
                    </ItemMedia>
                    <ItemContent className="min-w-0">
                        <ItemDescription className="line-clamp-none">
                            <span className="inline-flex flex-wrap items-center gap-1">
                                {exposureCriteria ? (
                                    <>
                                        Counts only after exposure event{' '}
                                        <Badge>
                                            {getExposureCriteriaLabel(exposureCriteria, resolvedExposureEvent)}
                                        </Badge>
                                        {activationConfig && (
                                            <>
                                                and activation event{' '}
                                                <Badge>{getExposureConfigDisplayName(activationConfig)}</Badge>
                                            </>
                                        )}
                                    </>
                                ) : usesWarehouseNative ? (
                                    <>Counts only after exposure. Each experiment sets its own exposure query.</>
                                ) : (
                                    <>
                                        Counts only after exposure event (<Badge>{resolvedExposureEvent}</Badge> by
                                        default)
                                    </>
                                )}
                                <QuillHelpTooltip
                                    label="exposure"
                                    help={
                                        <span className="flex flex-col gap-2">
                                            <span>{EXPOSURE_HELP}</span>
                                            <span>{exposureSharingHelp(!!exposureCriteria)}</span>
                                        </span>
                                    }
                                />
                            </span>
                        </ItemDescription>
                    </ItemContent>
                    {exposureCriteria && openExposureCriteriaModal && (
                        <ItemActions>
                            <Button
                                size="icon-xs"
                                aria-label="Edit exposure criteria"
                                tooltip="Edit exposure criteria"
                                onClick={() => openExposureCriteriaModal(exposureCriteria)}
                            >
                                <IconPencil />
                            </Button>
                        </ItemActions>
                    )}
                </Item>

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
                                {...seriesProps}
                                series={metricSourcesToSeries([metric.source])}
                                onChange={handleSetSeries}
                                typeKey="experiment-metric"
                                buttonCopy="Add graph series"
                                hideRename={true}
                                entitiesLimit={1}
                                showNumericalPropsOnly={true}
                            />
                        )}
                        {metric.source.math === ExperimentMetricMathType.HogQL && (
                            <Text size="xs" variant="muted">
                                {HOGQL_HELP}{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={HOGQL_DOCS_URL} target="_blank" />}
                                >
                                    Learn more about HogQL expressions
                                </Button>
                            </Text>
                        )}
                        <QuillMetricThreshold
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
                    <QuillQuantileMetricFields metric={metric} handleSetMetric={handleSetMetric} />
                )}

                {isExperimentFunnelMetric(metric) && (
                    <SeriesActionFilter
                        {...seriesProps}
                        series={metricSourcesToSeries(metric.series)}
                        onChange={handleSetSeries}
                        typeKey="experiment-metric"
                        buttonCopy="Add step"
                        hideRename={false}
                        hideDeleteBtn={hideDeleteBtn}
                        sortable={true}
                        showNestedArrow={true}
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
                    <FieldGroup>
                        <Field>
                            <FieldLabel>Numerator (what you're measuring)</FieldLabel>
                            <SeriesActionFilter
                                {...seriesProps}
                                series={metricSourcesToSeries([metric.numerator])}
                                onChange={(series) => {
                                    const source = seriesToMetricSource(series)
                                    if (source) {
                                        handleSetMetric({ ...metric, numerator: source })
                                    }
                                }}
                                typeKey="experiment-metric-numerator"
                                buttonCopy="Add numerator event"
                                hideRename={true}
                                entitiesLimit={1}
                                showNumericalPropsOnly={true}
                            />
                        </Field>
                        <Field>
                            <FieldLabel>Denominator (what you're dividing by)</FieldLabel>
                            <SeriesActionFilter
                                {...seriesProps}
                                series={metricSourcesToSeries([metric.denominator])}
                                onChange={(series) => {
                                    const source = seriesToMetricSource(series)
                                    if (source) {
                                        handleSetMetric({ ...metric, denominator: source })
                                    }
                                }}
                                typeKey="experiment-metric-denominator"
                                buttonCopy="Add denominator event"
                                hideRename={true}
                                entitiesLimit={1}
                            />
                        </Field>
                    </FieldGroup>
                )}

                {isExperimentRetentionMetric(metric) && (
                    <FieldGroup>
                        <FieldSet>
                            <span className="flex items-center gap-1">
                                <FieldLegend variant="label">Start event</FieldLegend>
                                <QuillHelpTooltip label="Start event" help={RETENTION_START_HELP} />
                            </span>
                            <RadioGroup
                                className="flex flex-row gap-4"
                                value={isExperimentExposureNode(metric.start_event) ? 'exposure' : 'custom'}
                                onValueChange={(value) => setRetentionStartSource(value as 'custom' | 'exposure')}
                                data-attr="experiment-retention-start-source"
                            >
                                {[
                                    { value: 'custom', label: 'Custom event' },
                                    { value: 'exposure', label: 'Experiment exposure' },
                                ].map((option) => (
                                    <Field key={option.value} orientation="horizontal" className="w-auto">
                                        <RadioGroupItem value={option.value} id={`retention-start-${option.value}`} />
                                        <Label htmlFor={`retention-start-${option.value}`}>{option.label}</Label>
                                    </Field>
                                ))}
                            </RadioGroup>
                            {isExperimentExposureNode(metric.start_event) ? (
                                <FieldDescription>{retentionExposureStartHelp(isSharedMetric)}</FieldDescription>
                            ) : (
                                <SeriesActionFilter
                                    {...seriesProps}
                                    series={metricSourcesToSeries([metric.start_event])}
                                    onChange={(series) => {
                                        const source = seriesToMetricSource(series)
                                        if (source) {
                                            handleSetMetric({ ...metric, start_event: source })
                                        }
                                    }}
                                    typeKey="experiment-metric-start-event"
                                    buttonCopy="Add start event"
                                    hideRename={true}
                                    entitiesLimit={1}
                                    showNumericalPropsOnly={true}
                                />
                            )}
                        </FieldSet>

                        <Field>
                            <LabelWithHelp label="Completion event" help={RETENTION_COMPLETION_HELP} />
                            <SeriesActionFilter
                                {...seriesProps}
                                series={metricSourcesToSeries([metric.completion_event])}
                                onChange={(series) => {
                                    const source = seriesToMetricSource(series)
                                    if (source) {
                                        handleSetMetric({ ...metric, completion_event: source })
                                    }
                                }}
                                typeKey="experiment-metric-completion-event"
                                buttonCopy="Add completion event"
                                hideRename={true}
                                entitiesLimit={1}
                                showNumericalPropsOnly={true}
                            />
                        </Field>

                        <Field>
                            <LabelWithHelp
                                htmlFor="retention-window-start"
                                label="Retention window"
                                help={
                                    <span className="flex flex-col gap-2">
                                        <span>{RETENTION_WINDOW_HELP}</span>
                                        <span>{RETENTION_WINDOW_EXAMPLE}</span>
                                    </span>
                                }
                            />
                            <span className="flex items-center gap-2">
                                <Text size="xs" variant="muted" render={<span />}>
                                    From
                                </Text>
                                <Input
                                    id="retention-window-start"
                                    type="number"
                                    min={0}
                                    className="w-20"
                                    value={metric.retention_window_start}
                                    onChange={(event) =>
                                        handleSetMetric({
                                            ...metric,
                                            retention_window_start: Number(event.target.value),
                                        })
                                    }
                                />
                                <Text size="xs" variant="muted" render={<span />}>
                                    to
                                </Text>
                                <Input
                                    type="number"
                                    aria-label="Retention window end"
                                    min={metric.retention_window_start || 0}
                                    className="w-20"
                                    value={metric.retention_window_end}
                                    onChange={(event) =>
                                        handleSetMetric({ ...metric, retention_window_end: Number(event.target.value) })
                                    }
                                />
                                <QuillSelect
                                    value={metric.retention_window_unit || FunnelConversionWindowTimeUnit.Day}
                                    options={RETENTION_UNIT_OPTIONS}
                                    onChange={(value) => handleSetMetric({ ...metric, retention_window_unit: value })}
                                    className="w-28"
                                />
                            </span>
                            <FieldDescription>
                                {isExperimentExposureNode(metric.start_event)
                                    ? "After the user's first exposure"
                                    : 'After the start event'}
                            </FieldDescription>
                        </Field>

                        {!isExperimentExposureNode(metric.start_event) && (
                            <Field>
                                <LabelWithHelp
                                    label="When users have multiple start events"
                                    help={START_HANDLING_HELP}
                                />
                                <QuillSelect
                                    value={metric.start_handling || 'first_seen'}
                                    options={START_HANDLING_OPTIONS}
                                    onChange={(value) =>
                                        handleSetMetric({
                                            ...metric,
                                            start_handling: value as 'first_seen' | 'last_seen',
                                        })
                                    }
                                />
                            </Field>
                        )}
                    </FieldGroup>
                )}
            </Section>
            <Separator />

            <Section title="Goal">
                <Field>
                    <QuillSelect
                        value={metric.goal || ExperimentMetricGoal.Increase}
                        options={GOAL_OPTIONS}
                        onChange={(goal) => handleSetMetric({ ...metric, goal })}
                        dataAttr="experiment-metric-goal"
                    />
                    <FieldDescription>{GOAL_HELP}</FieldDescription>
                </Field>
            </Section>
            <Separator />

            <QuillValueFormatSection metric={metric} handleSetMetric={handleSetMetric} />
            {/* The backend ignores the conversion window for exposure-anchored retention: the retention window already anchors on exposure */}
            {!(isExperimentRetentionMetric(metric) && isExperimentExposureNode(metric.start_event)) && (
                <>
                    <QuillConversionWindowSection metric={metric} handleSetMetric={handleSetMetric} />
                    <Separator />
                </>
            )}
            {isExperimentFunnelMetric(metric) && (
                <>
                    <QuillFunnelOrderSection metric={metric} handleSetMetric={handleSetMetric} />
                    <Separator />
                </>
            )}
            {isExperimentMeanMetric(metric) && (
                <>
                    <QuillOutlierHandlingSection metric={metric} handleSetMetric={handleSetMetric} />
                    {!usesWarehouseNative && <Separator />}
                </>
            )}
            {isExperimentRatioMetric(metric) && (
                <>
                    <QuillRatioOutlierHandlingSection metric={metric} handleSetMetric={handleSetMetric} />
                    {!usesWarehouseNative && <Separator />}
                </>
            )}
            {!usesWarehouseNative && (
                <Section
                    title="Recent activity"
                    help={
                        <span className="flex flex-col gap-2">
                            <span>{RECENT_ACTIVITY_HELP}</span>
                            <span>{RECENT_ACTIVITY_HEALTH_HELP}</span>
                            <span>
                                If you see zero activity, double-check that this metric is being tracked properly in
                                your application. Head to{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={urls.insightNew()} target="_blank" />}
                                >
                                    Product analytics
                                </Button>{' '}
                                to do a detailed analysis of the events received so far.
                            </span>
                        </span>
                    }
                >
                    <div className="rounded-md border border-border p-4" data-attr="experiment-metric-recent-activity">
                        {isLoading ? (
                            <span className="flex items-center gap-2">
                                <Spinner />
                                <Text size="xs" variant="muted" render={<span />}>
                                    Loading recent activity...
                                </Text>
                            </span>
                        ) : (
                            <span className="flex flex-col gap-1">
                                <Heading size="2xl" render={<span />}>
                                    {eventCount !== null ? eventCount.toLocaleString() : '0'}
                                </Heading>
                                <Text size="xs" variant="muted" render={<span />}>
                                    {eventCount !== null && eventCount > 0
                                        ? `${getEventTypeLabel()} in the past 2 weeks`
                                        : 'No recent activity'}
                                </Text>
                            </span>
                        )}
                    </div>
                </Section>
            )}
        </div>
    )
}
