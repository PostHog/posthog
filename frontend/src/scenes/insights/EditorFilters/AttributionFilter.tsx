import { useActions, useValues } from 'kea'
import { BreakdownAttributionType, QueryEditorFilterProps, StepOrderValue } from '~/types'
import { LemonSelect } from '@posthog/lemon-ui'
import { FunnelsFilter } from '~/queries/schema'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

export function Attribution({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { insightFilter, steps } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { breakdown_attribution_type, breakdown_attribution_value, funnel_order_type } = (insightFilter ||
        {}) as FunnelsFilter
    return (
        <LemonSelect
            value={breakdown_attribution_type || BreakdownAttributionType.FirstTouch}
            placeholder="Attribution"
            options={[
                { value: BreakdownAttributionType.FirstTouch, label: 'First touchpoint' },
                { value: BreakdownAttributionType.LastTouch, label: 'Last touchpoint' },
                { value: BreakdownAttributionType.AllSteps, label: 'All steps' },
                funnel_order_type === StepOrderValue.UNORDERED
                    ? { value: BreakdownAttributionType.Step, label: 'Any step' }
                    : {
                          value: BreakdownAttributionType.Step,
                          label: 'Specific step',
                          labelInMenuExtra: (
                              <LemonSelect
                                  className="ml-2"
                                  onChange={(value) => {
                                      if (value !== null) {
                                          updateInsightFilter({
                                              breakdown_attribution_type: BreakdownAttributionType.Step,
                                              breakdown_attribution_value: value,
                                          })
                                      }
                                  }}
                                  placeholder={`Step ${
                                      breakdown_attribution_value ? breakdown_attribution_value + 1 : 1
                                  }`}
                                  options={steps.map((_, idx) => ({ value: idx, label: `Step ${idx + 1}` }))}
                              />
                          ),
                      },
            ]}
            onChange={(value) => {
                if (value) {
                    updateInsightFilter({
                        breakdown_attribution_type: value,
                        breakdown_attribution_value: breakdown_attribution_value || 0,
                    })
                }
            }}
            dropdownMaxContentWidth={true}
            data-attr="breakdown-attributions"
        />
    )
}
