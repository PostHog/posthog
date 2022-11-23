import { useActions, useValues } from 'kea'
import { BreakdownAttributionType, EditorFilterProps, StepOrderValue } from '~/types'
import { LemonSelect } from '@posthog/lemon-ui'
import { funnelLogic } from 'scenes/funnels/funnelLogic'

export function Attribution({ insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(funnelLogic(insightProps))
    const { filters, breakdownAttributionStepOptions } = useValues(funnelLogic(insightProps))

    return (
        <LemonSelect
            value={filters.breakdown_attribution_type || BreakdownAttributionType.FirstTouch}
            placeholder="Attribution"
            options={[
                { value: BreakdownAttributionType.FirstTouch, label: 'First touchpoint' },
                { value: BreakdownAttributionType.LastTouch, label: 'Last touchpoint' },
                { value: BreakdownAttributionType.AllSteps, label: 'All steps' },
                filters.funnel_order_type === StepOrderValue.UNORDERED
                    ? { value: BreakdownAttributionType.Step, label: 'Any step' }
                    : {
                          value: BreakdownAttributionType.Step,
                          label: 'Specific step',
                          element: (
                              <LemonSelect
                                  className="ml-2"
                                  onChange={(value) => {
                                      if (value !== null) {
                                          setFilters({
                                              breakdown_attribution_type: BreakdownAttributionType.Step,
                                              breakdown_attribution_value: value,
                                          })
                                      }
                                  }}
                                  placeholder={`Step ${
                                      filters.breakdown_attribution_value ? filters.breakdown_attribution_value + 1 : 1
                                  }`}
                                  options={breakdownAttributionStepOptions}
                              />
                          ),
                      },
            ]}
            onChange={(value) => {
                if (value) {
                    setFilters({
                        breakdown_attribution_type: value,
                        breakdown_attribution_value: filters.breakdown_attribution_value || 0,
                    })
                }
            }}
            dropdownMaxContentWidth={true}
            data-attr="breakdown-attributions"
        />
    )
}
