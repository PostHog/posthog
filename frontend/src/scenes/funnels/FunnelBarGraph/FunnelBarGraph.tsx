import './FunnelBarGraph.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { IconInfinity, IconTrendingFlat, IconTrendingFlatDown } from 'lib/lemon-ui/icons'
import { humanFriendlyDuration, percentage, pluralize } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'

import { ChartParams, FunnelStepReference, StepOrderValue } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { FunnelStepMore } from '../FunnelStepMore'
import { getBreakdownMaxIndex, getReferenceStep } from '../funnelUtils'
import { ValueInspectorButton } from '../ValueInspectorButton'
import { Bar } from './Bar'
import { DuplicateStepIndicator } from './DuplicateStepIndicator'

export function FunnelBarGraph({
    inCardView,
    showPersonsModal: showPersonsModalProp = true,
}: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { visibleStepsWithConversionMetrics, aggregationTargetLabel, funnelsFilter } = useValues(
        funnelDataLogic(insightProps)
    )

    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForStep, openPersonsModalForSeries } = useActions(funnelPersonsModalLogic(insightProps))

    const { ref: graphRef, width } = useResizeObserver()

    const steps = visibleStepsWithConversionMetrics
    const stepReference = funnelsFilter?.funnel_step_reference || FunnelStepReference.total

    const showPersonsModal = canOpenPersonModal && showPersonsModalProp

    // Everything rendered after is a funnel in top-to-bottom mode.
    return (
        <div data-attr="funnel-bar-graph" className={clsx('FunnelBarGraph')} ref={graphRef}>
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
                            {funnelsFilter?.funnel_order_type === StepOrderValue.UNORDERED ? (
                                <SeriesGlyph variant="funnel-step-glyph">
                                    <IconInfinity style={{ fill: 'var(--primary_alt)', width: 14 }} />
                                </SeriesGlyph>
                            ) : (
                                <SeriesGlyph variant="funnel-step-glyph">{step.order + 1}</SeriesGlyph>
                            )}
                            <div className={`funnel-series-linebox ${showLineAfter ? 'after' : ''}`} />
                        </div>
                        <header>
                            <div className="flex items-center max-w-full grow">
                                <div className="funnel-step-title">
                                    {funnelsFilter?.funnel_order_type === StepOrderValue.UNORDERED ? (
                                        <span>Completed {step.order + 1} steps</span>
                                    ) : (
                                        <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
                                    )}
                                </div>
                                {funnelsFilter?.funnel_order_type !== StepOrderValue.UNORDERED &&
                                    stepIndex > 0 &&
                                    step.action_id === steps[stepIndex - 1].action_id && <DuplicateStepIndicator />}
                                <FunnelStepMore stepIndex={stepIndex} />
                            </div>
                            {step.average_conversion_time && step.average_conversion_time >= Number.EPSILON ? (
                                <div className="text-muted-alt">
                                    Average time to convert:{' '}
                                    <b>{humanFriendlyDuration(step.average_conversion_time, 2)}</b>
                                </div>
                            ) : null}
                        </header>
                        <div className="funnel-inner-viz">
                            <div className={clsx('funnel-bar-wrapper', { breakdown: isBreakdown })} aria-busy={!width}>
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
                                                        openPersonsModalForSeries({
                                                            step,
                                                            series: breakdown,
                                                            converted: true,
                                                        })
                                                    }
                                                    disabled={!showPersonsModal}
                                                    popoverTitle={
                                                        // eslint-disable-next-line react/forbid-dom-props
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
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{
                                                flex: `${1 - breakdownSum / basisStep.count} 1 0`,
                                                cursor: `${!inCardView ? 'pointer' : ''}`,
                                            }}
                                        />
                                    </>
                                ) : (
                                    <>
                                        <Bar
                                            percentage={step.conversionRates.fromBasisStep}
                                            name={step.name}
                                            onBarClick={() => openPersonsModalForStep({ step, converted: true })}
                                            disabled={!showPersonsModal}
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
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{
                                                flex: `${1 - step.conversionRates.fromBasisStep} 1 0`,
                                                cursor: `${!inCardView ? 'pointer' : ''}`,
                                            }}
                                        />
                                    </>
                                )}
                            </div>
                            <div className="funnel-conversion-metadata funnel-step-metadata">
                                <div>
                                    <ValueInspectorButton
                                        onClick={
                                            showPersonsModal
                                                ? () => openPersonsModalForStep({ step, converted: true })
                                                : undefined
                                        }
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
                                    </ValueInspectorButton>{' '}
                                    <span className="text-muted-alt grow">
                                        {`(${percentage(step.conversionRates.fromPrevious, 2, true)}) completed step`}
                                    </span>
                                </div>
                                {stepIndex > 0 && (
                                    <div>
                                        <ValueInspectorButton
                                            onClick={
                                                showPersonsModal
                                                    ? () => openPersonsModalForStep({ step, converted: false })
                                                    : undefined
                                            }
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
                                        </ValueInspectorButton>{' '}
                                        <span className="text-muted-alt">
                                            {`(${percentage(
                                                1 - step.conversionRates.fromPrevious,
                                                2,
                                                true
                                            )}) dropped off`}
                                        </span>
                                    </div>
                                )}
                            </div>
                        </div>
                    </section>
                )
            })}
        </div>
    )
}
