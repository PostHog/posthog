import { useActions, useValues } from 'kea'
import {
    BreakdownAttributionType,
    EditorFilterProps,
    FunnelStepWithNestedBreakdown,
    QueryEditorFilterProps,
    StepOrderValue,
} from '~/types'
import { LemonSelect } from '@posthog/lemon-ui'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelsFilter } from '~/queries/schema'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

export function AttributionDataExploration({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    // TODO: implement in funnelDataLogic
    const steps: FunnelStepWithNestedBreakdown[] = []

    return <AttributionComponent setFilters={updateInsightFilter} steps={steps} {...insightFilter} />
}

export function Attribution({ insightProps }: EditorFilterProps): JSX.Element {
    const { filters, steps } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))

    return <AttributionComponent setFilters={setFilters} steps={steps} {...filters} />
}

type AttributionComponentProps = {
    setFilters: (filters: FunnelsFilter) => void
    steps: FunnelStepWithNestedBreakdown[]
} & FunnelsFilter

export function AttributionComponent({
    breakdown_attribution_type,
    breakdown_attribution_value,
    funnel_order_type,
    setFilters,
    steps,
}: AttributionComponentProps): JSX.Element {
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
                                      breakdown_attribution_value ? breakdown_attribution_value + 1 : 1
                                  }`}
                                  options={steps.map((_, idx) => ({ value: idx, label: `Step ${idx + 1}` }))}
                              />
                          ),
                      },
            ]}
            onChange={(value) => {
                if (value) {
                    setFilters({
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
