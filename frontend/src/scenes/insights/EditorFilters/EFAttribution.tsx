import React from 'react'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { BreakdownAttributionType, EditorFilterProps, StepOrderValue } from '~/types'
import { LemonSelect } from '@posthog/lemon-ui'
import { funnelLogic } from 'scenes/funnels/funnelLogic'

export function EFAttribution({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))
    const { breakdownAttributionStepOptions } = useValues(funnelLogic(insightProps))

    return (
        <LemonSelect
            value={filters.breakdown_attribution_type || BreakdownAttributionType.FirstTouch}
            placeholder="Attribution"
            options={{
                [BreakdownAttributionType.FirstTouch]: { label: 'First touchpoint' },
                [BreakdownAttributionType.LastTouch]: { label: 'Last touchpoint' },
                [BreakdownAttributionType.AllSteps]: { label: 'All Steps' },
                ...(filters.funnel_order_type === StepOrderValue.UNORDERED
                    ? { [BreakdownAttributionType.Step]: { label: 'Any step' } }
                    : {
                          [BreakdownAttributionType.Step]: {
                              label: 'Specific step',
                              element: (
                                  <LemonSelect
                                      outlined
                                      className="ml-05"
                                      onChange={(value) => {
                                          if (value) {
                                              setFilters({
                                                  breakdown_attribution_type: BreakdownAttributionType.Step,
                                                  breakdown_attribution_value: parseInt(value),
                                              })
                                          }
                                      }}
                                      placeholder={`Step ${
                                          filters.breakdown_attribution_value
                                              ? filters.breakdown_attribution_value + 1
                                              : 1
                                      }`}
                                      options={breakdownAttributionStepOptions}
                                  />
                              ),
                          },
                      }),
            }}
            onChange={(value) => {
                if (value) {
                    setFilters({
                        breakdown_attribution_type: value,
                        breakdown_attribution_value: filters.breakdown_attribution_value || 0,
                    })
                }
            }}
            dropdownMaxContentWidth={true}
            outlined
            data-attr="breakdown-attributions"
        />
    )
}
