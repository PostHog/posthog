import {
    Button,
    Checkbox,
    Field,
    FieldDescription,
    FieldError,
    FieldLabel,
    Heading,
    Input,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Label,
    RadioGroup,
    RadioGroupItem,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SeriesActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'

import {
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetric,
    ExperimentMetricOutlierHandling as ExperimentMetricOutlierHandlingConfig,
    ExperimentQuantileMetric,
    ExperimentRatioMetric,
    ExperimentWarehouseNativeMathType,
    MathType,
} from '~/queries/schema/schema-general'
import { ChartDisplayCategory, FunnelConversionWindowTimeUnit, StepOrderValue } from '~/types'

import {
    type ValueFormatOption,
    VALUE_FORMAT_DESCRIPTION,
    useValueFormat,
    valueFormatChoices,
} from 'products/experiments/frontend/components/ExperimentMetricValueFormatSection'
import {
    PRESET_PERCENTILES,
    type PercentileOption,
    QUANTILE_PROPERTY_HELP,
    quantileExplanation,
    useQuantileMetricFields,
} from 'products/experiments/frontend/components/ExperimentQuantileMetricFields'
import { TIME_INTERVAL_BOUNDS } from 'products/product_analytics/frontend/insights/funnels/funnelUtils'

import {
    CONVERSION_WINDOW_MODES,
    ConversionWindowHelp,
    conversionWindowModeChange,
    conversionWindowUnitOptions,
} from './ExperimentMetricConversionWindowFilter'
import { StepOrderInfo, funnelOrderOptions } from './ExperimentMetricFunnelOrderSelector'
import {
    IGNORE_ZEROS_HELP,
    OUTLIER_DESCRIPTION,
    OUTLIER_DISABLED_BY_THRESHOLD,
    OUTLIER_DOCS_URL,
    OUTLIER_MEAN_HELP,
    OUTLIER_RATIO_HELP,
    normalizeOutlierHandling,
} from './ExperimentMetricOutlierHandling'
import {
    THRESHOLD_DISABLED_TOOLTIP,
    THRESHOLD_HELP,
    isMetricThresholdSet,
    isThresholdAvailableForMath,
    thresholdHint,
} from './ExperimentMetricThreshold'
import { QuillHelpTooltip } from './ExperimentView/QuillCardParts'
import { metricSourcesToSeries, seriesToMetricSource } from './metricQueryUtils'
import { commonActionFilterProps } from './Metrics/Selectors'

export function QuillFormSection({
    title,
    help,
    description,
    children,
}: {
    title: string
    help?: React.ReactNode
    description?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="flex max-w-prose flex-col gap-2">
            <span className="flex items-center gap-1">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    {title}
                </Heading>
                {help && <QuillHelpTooltip label={title} help={help} />}
            </span>
            {description && (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {description}
                </Text>
            )}
            {children}
        </section>
    )
}

function SimpleSelect<T extends string>({
    value,
    options,
    onChange,
    className,
    dataAttr,
    renderItem,
}: {
    value: T
    options: { value: T; label: string }[]
    onChange: (value: T) => void
    className?: string
    dataAttr?: string
    renderItem?: (option: { value: T; label: string }) => React.ReactNode
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
                        {renderItem ? renderItem(option) : option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}

export function QuillConversionWindowSection({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    const mode = metric.conversion_window_unit === undefined ? 'experiment_duration' : 'time_window'
    const intervalBounds = TIME_INTERVAL_BOUNDS[metric.conversion_window_unit ?? FunnelConversionWindowTimeUnit.Day]

    return (
        <QuillFormSection title="Conversion window limit" help={<ConversionWindowHelp />}>
            <RadioGroup
                className="flex flex-row gap-4"
                value={mode}
                onValueChange={(value) =>
                    handleSetMetric(conversionWindowModeChange(metric, value as 'experiment_duration' | 'time_window'))
                }
            >
                {CONVERSION_WINDOW_MODES.map((option) => (
                    <Field key={option.value} orientation="horizontal" className="w-auto">
                        <RadioGroupItem value={option.value} id={`conversion-window-${option.value}`} />
                        <Label htmlFor={`conversion-window-${option.value}`}>{option.label}</Label>
                    </Field>
                ))}
            </RadioGroup>
            {metric.conversion_window_unit !== undefined && (
                <span className="flex items-center gap-2">
                    <Input
                        type="number"
                        aria-label="Conversion window"
                        className="w-20"
                        min={intervalBounds[0]}
                        max={intervalBounds[1]}
                        value={metric.conversion_window ?? ''}
                        onChange={(event) =>
                            handleSetMetric({ ...metric, conversion_window: Number(event.target.value) || undefined })
                        }
                    />
                    <SimpleSelect
                        value={metric.conversion_window_unit}
                        options={conversionWindowUnitOptions(metric)}
                        onChange={(unit) => handleSetMetric({ ...metric, conversion_window_unit: unit })}
                        className="w-32"
                    />
                </span>
            )}
        </QuillFormSection>
    )
}

export function QuillFunnelOrderSection({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentFunnelMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    return (
        <QuillFormSection title="Step order" help={<StepOrderInfo />}>
            <SimpleSelect
                value={metric.funnel_order_type || StepOrderValue.ORDERED}
                options={funnelOrderOptions}
                onChange={(funnelOrderType) => handleSetMetric({ ...metric, funnel_order_type: funnelOrderType })}
                dataAttr="experiment-funnel-order-selector"
            />
        </QuillFormSection>
    )
}

export function QuillMetricThreshold({
    math,
    value,
    onChange,
}: {
    math: MathType | ExperimentWarehouseNativeMathType | undefined
    value: number | undefined
    onChange: (value: number | undefined) => void
}): JSX.Element {
    const enabled = isThresholdAvailableForMath(math)

    return (
        <Field>
            <span className="flex items-center gap-1">
                <FieldLabel htmlFor="experiment-metric-threshold">Threshold</FieldLabel>
                <QuillHelpTooltip label="Threshold" help={THRESHOLD_HELP} />
            </span>
            <Input
                id="experiment-metric-threshold"
                type="number"
                className="w-32"
                min={0}
                step={1}
                placeholder="e.g. 100"
                value={value ?? ''}
                disabled={!enabled}
                title={enabled ? undefined : THRESHOLD_DISABLED_TOOLTIP}
                // Treat empty, cleared (0) and NaN as "no threshold" so dependent fields re-enable.
                onChange={(event) => onChange(Number(event.target.value) || undefined)}
            />
            <FieldDescription>{thresholdHint(enabled)}</FieldDescription>
        </Field>
    )
}

function PercentInput({
    value,
    onChange,
    label,
    hidden,
}: {
    value: number | undefined
    onChange: (value: number) => void
    label: string
    hidden: boolean
}): JSX.Element {
    return (
        <InputGroup size="sm" className={hidden ? 'invisible w-24' : 'w-24'}>
            <InputGroupInput
                type="number"
                step={1}
                aria-label={label}
                value={value !== undefined ? value * 100 : 0}
                onChange={(event) => onChange(Number(event.target.value) / 100)}
            />
            <InputGroupAddon align="inline-end">%</InputGroupAddon>
        </InputGroup>
    )
}

function QuillOutlierControls({
    value,
    onChange,
    disabled = false,
    idPrefix,
}: {
    value: ExperimentMetricOutlierHandlingConfig
    onChange: (next: ExperimentMetricOutlierHandlingConfig) => void
    disabled?: boolean
    idPrefix: string
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <span className="flex items-center gap-2">
                <Field orientation="horizontal" className="w-56">
                    <Checkbox
                        id={`${idPrefix}-lower`}
                        disabled={disabled}
                        checked={value.lower_bound_percentile !== undefined}
                        onCheckedChange={(checked) =>
                            onChange({ ...value, lower_bound_percentile: checked ? 0.05 : undefined })
                        }
                    />
                    <Label htmlFor={`${idPrefix}-lower`}>Lower bound percentile</Label>
                </Field>
                <PercentInput
                    label="Lower bound percentile"
                    value={value.lower_bound_percentile}
                    hidden={value.lower_bound_percentile === undefined}
                    onChange={(next) =>
                        value.lower_bound_percentile !== undefined &&
                        onChange({ ...value, lower_bound_percentile: next })
                    }
                />
            </span>
            <span className="flex flex-wrap items-center gap-2">
                <Field orientation="horizontal" className="w-56">
                    <Checkbox
                        id={`${idPrefix}-upper`}
                        disabled={disabled}
                        checked={value.upper_bound_percentile !== undefined}
                        onCheckedChange={(checked) =>
                            onChange({ ...value, upper_bound_percentile: checked ? 0.95 : undefined })
                        }
                    />
                    <Label htmlFor={`${idPrefix}-upper`}>Upper bound percentile</Label>
                </Field>
                <PercentInput
                    label="Upper bound percentile"
                    value={value.upper_bound_percentile}
                    hidden={value.upper_bound_percentile === undefined}
                    onChange={(next) =>
                        value.upper_bound_percentile !== undefined &&
                        onChange({ ...value, upper_bound_percentile: next })
                    }
                />
                {value.upper_bound_percentile !== undefined && (
                    <Field orientation="horizontal">
                        <Checkbox
                            id={`${idPrefix}-ignore-zeros`}
                            disabled={disabled}
                            checked={value.ignore_zeros ?? false}
                            onCheckedChange={(checked) => onChange({ ...value, ignore_zeros: !!checked })}
                        />
                        <Label htmlFor={`${idPrefix}-ignore-zeros`}>Ignore zeros when calculating upper bound</Label>
                        <QuillHelpTooltip
                            label="ignoring zeros"
                            help={
                                <span className="flex flex-col gap-1">
                                    <span>{IGNORE_ZEROS_HELP}</span>
                                    <Button
                                        variant="link"
                                        size="inline"
                                        nativeButton={false}
                                        render={<LinkPrimitive to={OUTLIER_DOCS_URL} target="_blank" />}
                                    >
                                        Read the docs
                                    </Button>
                                </span>
                            }
                        />
                    </Field>
                )}
            </span>
        </div>
    )
}

export function QuillOutlierHandlingSection({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMeanMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    // Winsorization caps continuous outliers, which is meaningless once a threshold collapses the metric into a binary outcome.
    const disabledByThreshold = isMetricThresholdSet(metric)

    return (
        <QuillFormSection
            title="Outlier handling"
            help={OUTLIER_MEAN_HELP}
            description={disabledByThreshold ? OUTLIER_DISABLED_BY_THRESHOLD : OUTLIER_DESCRIPTION}
        >
            <QuillOutlierControls
                idPrefix="outlier"
                disabled={disabledByThreshold}
                value={{
                    lower_bound_percentile: metric.lower_bound_percentile,
                    upper_bound_percentile: metric.upper_bound_percentile,
                    ignore_zeros: metric.ignore_zeros,
                }}
                onChange={(next) => handleSetMetric({ ...metric, ...next })}
            />
        </QuillFormSection>
    )
}

export function QuillRatioOutlierHandlingSection({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentRatioMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    return (
        <QuillFormSection title="Outlier handling" help={OUTLIER_RATIO_HELP} description={OUTLIER_DESCRIPTION}>
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-2">
                    <Text size="xs" weight="medium" render={<span />}>
                        Numerator
                    </Text>
                    <QuillOutlierControls
                        idPrefix="outlier-numerator"
                        value={metric.numerator_outlier_handling ?? {}}
                        onChange={(next) =>
                            handleSetMetric({ ...metric, numerator_outlier_handling: normalizeOutlierHandling(next) })
                        }
                    />
                </div>
                <div className="flex flex-col gap-2">
                    <Text size="xs" weight="medium" render={<span />}>
                        Denominator
                    </Text>
                    <QuillOutlierControls
                        idPrefix="outlier-denominator"
                        value={metric.denominator_outlier_handling ?? {}}
                        onChange={(next) =>
                            handleSetMetric({
                                ...metric,
                                denominator_outlier_handling: normalizeOutlierHandling(next),
                            })
                        }
                    />
                </div>
            </div>
        </QuillFormSection>
    )
}

export function QuillValueFormatSection({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element | null {
    const { visible, value, baseCurrency, onChange } = useValueFormat(metric, handleSetMetric)
    if (!visible) {
        return null
    }
    const choices = valueFormatChoices(baseCurrency)

    return (
        <>
            <QuillFormSection title="Value format" description={VALUE_FORMAT_DESCRIPTION}>
                <SimpleSelect<ValueFormatOption>
                    value={value}
                    options={choices}
                    onChange={onChange}
                    dataAttr="experiment-metric-value-format-select"
                    renderItem={(option) => {
                        const example = choices.find((choice) => choice.value === option.value)?.example
                        return (
                            <span className="flex w-full flex-wrap items-center justify-between gap-x-4">
                                <span>{option.label}</span>
                                {example && (
                                    <Text size="xs" variant="muted" render={<span translate="no" />}>
                                        {example}
                                    </Text>
                                )}
                            </span>
                        )
                    }}
                />
            </QuillFormSection>
            <Separator />
        </>
    )
}

export function QuillQuantileMetricFields({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentQuantileMetric
    handleSetMetric: (newMetric: ExperimentQuantileMetric) => void
}): JSX.Element {
    const {
        percentile,
        isCustom,
        customPercentile,
        customPercentileError,
        eventName,
        pickPercentile,
        setCustom,
        setSource,
        setProperty,
    } = useQuantileMetricFields(metric, handleSetMetric)

    return (
        <div className="flex flex-col gap-4">
            <SeriesActionFilter
                bordered
                series={metricSourcesToSeries([metric.source])}
                trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
                onChange={(series) => setSource(seriesToMetricSource(series))}
                typeKey="experiment-metric-quantile"
                buttonCopy="Add event"
                showSeriesIndicator={false}
                hideRename={true}
                entitiesLimit={1}
                mathAvailability={MathAvailability.None}
                {...commonActionFilterProps}
                actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
            />
            <Field>
                <FieldLabel>Property</FieldLabel>
                <TaxonomicStringPopover
                    type="secondary"
                    groupType={TaxonomicFilterGroupType.NumericalEventProperties}
                    groupTypes={[TaxonomicFilterGroupType.NumericalEventProperties]}
                    value={metric.source.math_property}
                    onChange={setProperty}
                    eventNames={eventName ? [eventName] : []}
                    placeholder="Select a numeric property"
                    showNumericalPropsOnly
                    selectingKeyOnly
                    renderValue={(value) => (
                        <PropertyKeyInfo value={value} disablePopover type={TaxonomicFilterGroupType.EventProperties} />
                    )}
                    data-attr="experiment-quantile-property-select"
                />
                <FieldDescription>{QUANTILE_PROPERTY_HELP}</FieldDescription>
            </Field>
            <Field data-invalid={customPercentileError ? true : undefined}>
                <FieldLabel>Percentile</FieldLabel>
                <span className="flex flex-wrap items-center gap-2">
                    <ToggleGroup
                        variant="outline"
                        size="sm"
                        value={[isCustom ? 'custom' : String(percentile)]}
                        onValueChange={(next: string[]) => {
                            const picked = next[0]
                            if (picked) {
                                pickPercentile((picked === 'custom' ? 'custom' : Number(picked)) as PercentileOption)
                            }
                        }}
                    >
                        {PRESET_PERCENTILES.map((value) => (
                            <ToggleGroupItem
                                key={value}
                                value={String(value)}
                                data-attr={`experiment-quantile-p${value}`}
                            >
                                p{value}
                            </ToggleGroupItem>
                        ))}
                        <ToggleGroupItem value="custom">Custom</ToggleGroupItem>
                    </ToggleGroup>
                    {isCustom && (
                        <InputGroup size="sm" className="w-24">
                            <InputGroupAddon align="inline-start">p</InputGroupAddon>
                            <InputGroupInput
                                type="number"
                                aria-label="Custom percentile"
                                step={0.1}
                                value={customPercentile ?? ''}
                                aria-invalid={customPercentileError ? true : undefined}
                                onChange={(event) =>
                                    setCustom(event.target.value === '' ? undefined : Number(event.target.value))
                                }
                                data-attr="experiment-quantile-custom-percentile"
                            />
                        </InputGroup>
                    )}
                </span>
                {customPercentileError ? (
                    <FieldError>{customPercentileError}</FieldError>
                ) : (
                    <FieldDescription>{quantileExplanation(percentile)}</FieldDescription>
                )}
            </Field>
        </div>
    )
}
