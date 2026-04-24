import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { Link } from '@posthog/lemon-ui'
import { LemonSelect } from '@posthog/lemon-ui'

import { FUNNEL_STEP_COUNT_LIMIT } from '~/scenes/insights/EditorFilters/FunnelsQuerySteps'
import { BreakdownAttributionType, StepOrderValue } from '~/types'

/**
 * @deprecated
 * Legacy funnel attribution select for ExperimentView.
 * Frozen copy for legacy experiments - do not modify.
 * Forked from https://github.com/PostHog/posthog/blob/master/frontend/src/scenes/insights/EditorFilters/AttributionFilter.tsx
 */
export function LegacyFunnelAttributionSelect({
    value,
    onChange,
    stepsLength,
}: {
    value: BreakdownAttributionType | `${BreakdownAttributionType.Step}/${number}`
    onChange: (value: BreakdownAttributionType | `${BreakdownAttributionType.Step}/${number}`) => void
    stepsLength: number
}): JSX.Element {
    const funnelOrderType = undefined

    return (
        <div className="flex items-center w-full gap-2">
            <div className="flex">
                <span>Attribution type</span>
                <Tooltip
                    closeDelayMs={200}
                    title={
                        <div className="deprecated-space-y-2">
                            <div>
                                When breaking down funnels, it's possible that the same properties don't exist on every
                                event. For example, if you want to break down by browser on a funnel that contains both
                                frontend and backend events.
                            </div>
                            <div>
                                In this case, you can choose from which step the properties should be selected from by
                                modifying the attribution type. There are four modes to choose from:
                            </div>
                            <ul className="list-disc pl-4">
                                <li>First touchpoint: the first property value seen in any of the steps is chosen.</li>
                                <li>Last touchpoint: the last property value seen from all steps is chosen.</li>
                                <li>
                                    All steps: the property value must be seen in all steps to be considered in the
                                    funnel.
                                </li>
                                <li>Specific step: only the property value seen at the selected step is chosen.</li>
                            </ul>
                            <div>
                                Read more in the{' '}
                                <Link to="https://posthog.com/docs/product-analytics/funnels#attribution-types">
                                    documentation.
                                </Link>
                            </div>
                        </div>
                    }
                >
                    <IconInfo className="text-xl text-secondary shrink-0 ml-1" />
                </Tooltip>
            </div>
            <LemonSelect
                value={value}
                placeholder="Attribution"
                options={[
                    { value: BreakdownAttributionType.FirstTouch, label: 'First touchpoint' },
                    { value: BreakdownAttributionType.LastTouch, label: 'Last touchpoint' },
                    { value: BreakdownAttributionType.AllSteps, label: 'All steps' },
                    {
                        value: BreakdownAttributionType.Step,
                        label: 'Any step',
                        hidden: funnelOrderType !== StepOrderValue.UNORDERED,
                    },
                    {
                        label: 'Specific step',
                        options: Array(FUNNEL_STEP_COUNT_LIMIT)
                            .fill(null)
                            .map((_, stepIndex) => ({
                                value: `${BreakdownAttributionType.Step}/${stepIndex}` as const,
                                label: `Step ${stepIndex + 1}`,
                                hidden: stepIndex >= stepsLength,
                            })),
                        hidden: funnelOrderType === StepOrderValue.UNORDERED,
                    },
                ]}
                onChange={onChange}
                dropdownMaxContentWidth={true}
                data-attr="breakdown-attributions"
            />
        </div>
    )
}
