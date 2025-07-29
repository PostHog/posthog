import './FunnelBarHorizontal.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
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

export function FunnelBarHorizontal({
    inCardView,
    showPersonsModal: showPersonsModalProp = true,
}: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { visibleStepsWithConversionMetrics, aggregationTargetLabel, funnelsFilter, breakdownFilter } = useValues(
        funnelDataLogic(insightProps)
    )

    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForStep, openPersonsModalForSeries } = useActions(funnelPersonsModalLogic(insightProps))

    const steps = visibleStepsWithConversionMetrics
    const stepReference = funnelsFilter?.funnelStepReference || FunnelStepReference.total

    const showPersonsModal = canOpenPersonModal && showPersonsModalProp

    // Everything rendered after is a funnel in top-to-bottom mode.
    return (
        <div data-attr="funnel-bar-horizontal" className={clsx('FunnelBarHorizontal')}>
            {steps.map((step, stepIndex) => {
                const basisStep = getReferenceStep(steps, stepReference, stepIndex)
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
                            {funnelsFilter?.funnelOrderType === StepOrderValue.UNORDERED ? (
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
                                    {funnelsFilter?.funnelOrderType === StepOrderValue.UNORDERED ? (
                                        <span>Completed {step.order + 1} steps</span>
                                    ) : (
                                        <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
                                    )}
                                </div>
                                {funnelsFilter?.funnelOrderType !== StepOrderValue.UNORDERED &&
                                    stepIndex > 0 &&
                                    step.action_id === steps[stepIndex - 1].action_id && <DuplicateStepIndicator />}
                                <FunnelStepMore stepIndex={stepIndex} />
                            </div>
                            {step.average_conversion_time && step.average_conversion_time >= Number.EPSILON ? (
                                <div className="text-secondary">
                                    Average time to convert:{' '}
                                    <b>{humanFriendlyDuration(step.average_conversion_time, { maxUnits: 2 })}</b>
                                </div>
                            ) : null}
                        </header>
                        <div className={clsx('funnel-bar-wrapper', { breakdown: isBreakdown })}>
                            {isBreakdown ? (
                                <>
                                    {step?.nested_breakdown?.map((breakdown, index) => {
                                        return (
                                            <Bar
                                                name={breakdown.name}
                                                percentage={breakdown.count / basisStep.count}
                                                key={`${breakdown.action_id}-${step.breakdown_value}-${index}`}
                                                isBreakdown={true}
                                                breakdownIndex={index}
                                                breakdownMaxIndex={breakdownMaxIndex}
                                                breakdownSumPercentage={
                                                    index === breakdownMaxIndex && breakdownSum
                                                        ? breakdownSum / basisStep.count
                                                        : undefined
                                                }
                                                onBarClick={() =>
                                                    openPersonsModalForSeries({
                                                        step,
                                                        series: breakdown,
                                                        converted: true,
                                                    })
                                                }
                                                step={breakdown}
                                                stepIndex={stepIndex}
                                                breakdownFilter={breakdownFilter}
                                                disabled={!showPersonsModal}
                                                aggregationTargetLabel={aggregationTargetLabel}
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
                                        name={step.name}
                                        percentage={step.conversionRates.fromBasisStep}
                                        onBarClick={() => openPersonsModalForStep({ step, converted: true })}
                                        step={step.nested_breakdown![0]}
                                        stepIndex={stepIndex}
                                        breakdownFilter={breakdownFilter}
                                        disabled={!showPersonsModal}
                                        aggregationTargetLabel={aggregationTargetLabel}
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
                                <span className="text-secondary grow">
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
                                    <span className="text-secondary">
                                        {`(${percentage(1 - step.conversionRates.fromPrevious, 2, true)}) dropped off`}
                                    </span>
                                </div>
                            )}
                        </div>
                    </section>
                )
            })}
        </div>
    )
}
