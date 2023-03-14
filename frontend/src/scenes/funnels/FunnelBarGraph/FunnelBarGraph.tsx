import clsx from 'clsx'
import { humanFriendlyDuration, percentage, pluralize } from 'lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { IconTrendingFlatDown, IconInfinity, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { funnelLogic } from '../funnelLogic'
import './FunnelBarGraph.scss'
import { useActions, useValues } from 'kea'
import { FunnelLayout } from 'lib/constants'
import { getBreakdownMaxIndex, getReferenceStep } from '../funnelUtils'
import { ChartParams, FunnelStepReference, StepOrderValue } from '~/types'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { FunnelStepMore } from '../FunnelStepMore'
import { ValueInspectorButton } from '../ValueInspectorButton'
import { DuplicateStepIndicator } from './DuplicateStepIndicator'
import { Bar } from './Bar'
import { AverageTimeInspector } from './AverageTimeInspector'

export function FunnelBarGraph(props: ChartParams): JSX.Element {
    const {
        filters,
        visibleStepsWithConversionMetrics: steps,
        stepReference,
        aggregationTargetLabel,
        isInDashboardContext,
    } = useValues(funnelLogic)
    const { openPersonsModalForStep } = useActions(funnelLogic)

    const { ref: graphRef, width } = useResizeObserver()

    // Everything rendered after is a funnel in top-to-bottom mode.
    return (
        <div data-attr="funnel-bar-graph" className={clsx('funnel-bar-graph', 'white')} ref={graphRef}>
            {steps.map((step, stepIndex) => {
                const basisStep = getReferenceStep(steps, stepReference, stepIndex)
                const previousStep = getReferenceStep(steps, FunnelStepReference.previous, stepIndex)
                const showLineBefore = stepIndex > 0
                const showLineAfter = stepIndex < steps.length - 1
                const breakdownMaxIndex = getBreakdownMaxIndex(
                    Array.isArray(step.nested_breakdown) ? step.nested_breakdown : undefined
                )
                const breakdownSum =
                    (Array.isArray(step.nested_breakdown) &&
                        step.nested_breakdown?.reduce((sum, item) => sum + item.count, 0)) ||
                    0

                const isBreakdown =
                    Array.isArray(step.nested_breakdown) &&
                    step.nested_breakdown?.length !== undefined &&
                    !(step.nested_breakdown.length === 1)

                const dropOffCount = step.order > 0 ? steps[stepIndex - 1].count - step.count : 0

                return (
                    <section key={step.order} className="funnel-step">
                        <div className="funnel-series-container">
                            <div className={`funnel-series-linebox ${showLineBefore ? 'before' : ''}`} />
                            {filters.funnel_order_type === StepOrderValue.UNORDERED ? (
                                <SeriesGlyph variant="funnel-step-glyph">
                                    <IconInfinity style={{ fill: 'var(--primary_alt)', width: 14 }} />
                                </SeriesGlyph>
                            ) : (
                                <SeriesGlyph variant="funnel-step-glyph">{step.order + 1}</SeriesGlyph>
                            )}
                            <div className={`funnel-series-linebox ${showLineAfter ? 'after' : ''}`} />
                        </div>
                        <header>
                            <div style={{ display: 'flex', alignItems: 'center', maxWidth: '100%', flexGrow: 1 }}>
                                <div className="funnel-step-title">
                                    {filters.funnel_order_type === StepOrderValue.UNORDERED ? (
                                        <span>Completed {step.order + 1} steps</span>
                                    ) : (
                                        <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
                                    )}
                                </div>
                                {filters.funnel_order_type !== StepOrderValue.UNORDERED &&
                                    stepIndex > 0 &&
                                    step.action_id === steps[stepIndex - 1].action_id && <DuplicateStepIndicator />}
                                <FunnelStepMore stepIndex={stepIndex} />
                            </div>
                            <div className={`funnel-step-metadata funnel-time-metadata ${FunnelLayout.horizontal}`}>
                                {step.average_conversion_time && step.average_conversion_time >= 0 + Number.EPSILON ? (
                                    <AverageTimeInspector
                                        onClick={() => {}}
                                        averageTime={step.average_conversion_time}
                                        aggregationTargetLabel={aggregationTargetLabel}
                                        disabled
                                    />
                                ) : null}
                            </div>
                        </header>
                        <div className="funnel-inner-viz">
                            <div className={clsx('funnel-bar-wrapper', { breakdown: isBreakdown })}>
                                {!width ? null : isBreakdown ? (
                                    <>
                                        {step?.nested_breakdown?.map((breakdown, index) => {
                                            const barSizePercentage = breakdown.count / basisStep.count
                                            return (
                                                <Bar
                                                    key={`${breakdown.action_id}-${step.breakdown_value}-${index}`}
                                                    isBreakdown={true}
                                                    breakdownIndex={index}
                                                    breakdownMaxIndex={breakdownMaxIndex}
                                                    breakdownSumPercentage={
                                                        index === breakdownMaxIndex && breakdownSum
                                                            ? breakdownSum / basisStep.count
                                                            : undefined
                                                    }
                                                    percentage={barSizePercentage}
                                                    name={breakdown.name}
                                                    onBarClick={() =>
                                                        openPersonsModalForStep({
                                                            step,
                                                            converted: true,
                                                        })
                                                    }
                                                    disabled={isInDashboardContext}
                                                    popoverTitle={
                                                        <div style={{ wordWrap: 'break-word' }}>
                                                            <PropertyKeyInfo value={step.name} />
                                                            {' • '}
                                                            {(Array.isArray(breakdown.breakdown)
                                                                ? breakdown.breakdown.join(', ')
                                                                : breakdown.breakdown) || 'Other'}
                                                        </div>
                                                    }
                                                    popoverMetrics={[
                                                        {
                                                            title: 'Completed step',
                                                            value: pluralize(
                                                                breakdown.count,
                                                                aggregationTargetLabel.singular,
                                                                aggregationTargetLabel.plural
                                                            ),
                                                        },
                                                        {
                                                            title: 'Conversion rate (total)',
                                                            value: percentage(breakdown.conversionRates.total, 2, true),
                                                        },
                                                        {
                                                            title: `Conversion rate (from step ${
                                                                previousStep.order + 1
                                                            })`,
                                                            value: percentage(
                                                                breakdown.conversionRates.fromPrevious,
                                                                2,
                                                                true
                                                            ),
                                                            visible: step.order !== 0,
                                                        },
                                                        {
                                                            title: 'Dropped off',
                                                            value: pluralize(
                                                                breakdown.droppedOffFromPrevious,
                                                                aggregationTargetLabel.singular,
                                                                aggregationTargetLabel.plural
                                                            ),
                                                            visible:
                                                                step.order !== 0 &&
                                                                breakdown.droppedOffFromPrevious > 0,
                                                        },
                                                        {
                                                            title: `Drop-off rate (from step ${
                                                                previousStep.order + 1
                                                            })`,
                                                            value: percentage(
                                                                1 - breakdown.conversionRates.fromPrevious,
                                                                2,
                                                                true
                                                            ),
                                                            visible:
                                                                step.order !== 0 &&
                                                                breakdown.droppedOffFromPrevious > 0,
                                                        },
                                                        {
                                                            title: 'Average time on step',
                                                            value: humanFriendlyDuration(
                                                                breakdown.average_conversion_time
                                                            ),
                                                            visible: !!breakdown.average_conversion_time,
                                                        },
                                                    ]}
                                                    aggregationTargetLabel={aggregationTargetLabel}
                                                    wrapperWidth={width}
                                                />
                                            )
                                        })}
                                        <div
                                            className="funnel-bar-empty-space"
                                            onClick={() => openPersonsModalForStep({ step, converted: false })} // dropoff value for steps is negative
                                            style={{
                                                flex: `${1 - breakdownSum / basisStep.count} 1 0`,
                                                cursor: `${!props.inCardView ? 'pointer' : ''}`,
                                            }}
                                        />
                                    </>
                                ) : (
                                    <>
                                        <Bar
                                            percentage={step.conversionRates.fromBasisStep}
                                            name={step.name}
                                            onBarClick={() => openPersonsModalForStep({ step, converted: true })}
                                            disabled={isInDashboardContext}
                                            popoverTitle={<PropertyKeyInfo value={step.name} />}
                                            popoverMetrics={[
                                                {
                                                    title: 'Completed step',
                                                    value: pluralize(
                                                        step.count,
                                                        aggregationTargetLabel.singular,
                                                        aggregationTargetLabel.plural
                                                    ),
                                                },
                                                {
                                                    title: 'Conversion rate (total)',
                                                    value: percentage(step.conversionRates.total, 2, true),
                                                },
                                                {
                                                    title: `Conversion rate (from step ${previousStep.order + 1})`,
                                                    value: percentage(step.conversionRates.fromPrevious, 2, true),
                                                    visible: step.order !== 0,
                                                },
                                                {
                                                    title: 'Dropped off',
                                                    value: pluralize(
                                                        step.droppedOffFromPrevious,
                                                        aggregationTargetLabel.singular,
                                                        aggregationTargetLabel.plural
                                                    ),
                                                    visible: step.order !== 0 && step.droppedOffFromPrevious > 0,
                                                },
                                                {
                                                    title: `Drop-off rate (from step ${previousStep.order + 1})`,
                                                    value: percentage(1 - step.conversionRates.fromPrevious, 2, true),
                                                    visible: step.order !== 0 && step.droppedOffFromPrevious > 0,
                                                },
                                                {
                                                    title: 'Average time on step',
                                                    value: humanFriendlyDuration(step.average_conversion_time),
                                                    visible: !!step.average_conversion_time,
                                                },
                                            ]}
                                            aggregationTargetLabel={aggregationTargetLabel}
                                            wrapperWidth={width}
                                        />
                                        <div
                                            className="funnel-bar-empty-space"
                                            onClick={() => openPersonsModalForStep({ step, converted: false })} // dropoff value for steps is negative
                                            style={{
                                                flex: `${1 - step.conversionRates.fromBasisStep} 1 0`,
                                                cursor: `${!props.inCardView ? 'pointer' : ''}`,
                                            }}
                                        />
                                    </>
                                )}
                            </div>
                            <div className="funnel-conversion-metadata funnel-step-metadata">
                                <div className="step-stat">
                                    <div className="center-flex">
                                        <ValueInspectorButton
                                            onClick={() => openPersonsModalForStep({ step, converted: true })}
                                            disabled={isInDashboardContext}
                                        >
                                            <IconTrendingFlat
                                                style={{ color: 'var(--success)' }}
                                                className="value-inspector-button-icon"
                                            />
                                            <b>
                                                {pluralize(
                                                    step.count,
                                                    aggregationTargetLabel.singular,
                                                    aggregationTargetLabel.plural
                                                )}
                                            </b>
                                        </ValueInspectorButton>
                                        <span className="text-muted-alt">
                                            (
                                            {percentage(
                                                step.order > 0 ? step.count / steps[stepIndex - 1].count : 1,
                                                2,
                                                true
                                            )}
                                            )
                                        </span>
                                    </div>
                                    <div className="text-muted-alt conversion-metadata-caption" style={{ flexGrow: 1 }}>
                                        completed step
                                    </div>
                                </div>
                                <div className={clsx('step-stat', stepIndex === 0 && 'invisible')}>
                                    <div className="center-flex">
                                        <ValueInspectorButton
                                            onClick={() => openPersonsModalForStep({ step, converted: false })}
                                            disabled={isInDashboardContext}
                                        >
                                            <IconTrendingFlatDown
                                                style={{ color: 'var(--danger)' }}
                                                className="value-inspector-button-icon"
                                            />
                                            <b>
                                                {pluralize(
                                                    dropOffCount,
                                                    aggregationTargetLabel.singular,
                                                    aggregationTargetLabel.plural
                                                )}
                                            </b>
                                        </ValueInspectorButton>
                                        <span className="text-muted-alt">
                                            (
                                            {percentage(
                                                step.order > 0 ? 1 - step.count / steps[stepIndex - 1].count : 0,
                                                2,
                                                true
                                            )}
                                            )
                                        </span>
                                    </div>
                                    <div className="text-muted-alt conversion-metadata-caption">dropped off</div>
                                </div>
                            </div>
                        </div>
                    </section>
                )
            })}
        </div>
    )
}
