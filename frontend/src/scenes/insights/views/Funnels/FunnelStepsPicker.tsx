import { LemonSelect, LemonSelectOption, LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { seriesNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'

export function FunnelStepsPicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { series, isFunnelWithEnoughSteps, funnelsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const onChange = (funnel_from_step?: number, funnel_to_step?: number): void => {
        updateInsightFilter({ funnel_from_step, funnel_to_step })
    }

    const filterSteps = series || []
    const numberOfSeries = series?.length || 0
    const fromRange = isFunnelWithEnoughSteps ? Array.from(Array(Math.max(numberOfSeries)).keys()).slice(0, -1) : [0]
    const toRange = isFunnelWithEnoughSteps
        ? Array.from(Array(Math.max(numberOfSeries)).keys()).slice((funnelsFilter?.funnel_from_step ?? 0) + 1)
        : [1]

    const optionsForRange = (range: number[]): LemonSelectOptions<number> => {
        return range
            .map((stepIndex): LemonSelectOption<number> | null => {
                return filterSteps[stepIndex]
                    ? {
                          value: stepIndex,
                          label: `Step ${stepIndex + 1}`,
                          labelInMenu: (
                              <>
                                  <span>Step {stepIndex + 1} – </span>
                                  <EntityFilterInfo filter={seriesNodeToFilter(filterSteps[stepIndex])} />
                              </>
                          ),
                      }
                    : null
            })
            .filter((option): option is LemonSelectOption<number> => option !== null)
    }

    return (
        <div className="flex items-center">
            <span className="text-muted-alt">&nbsp;from</span>
            <LemonSelect
                size="small"
                className="mx-1"
                dropdownMatchSelectWidth={false}
                optionTooltipPlacement="bottomLeft"
                disabled={!isFunnelWithEnoughSteps}
                options={optionsForRange(fromRange)}
                value={funnelsFilter?.funnel_from_step || 0}
                onChange={(fromStep: number | null) =>
                    fromStep != null && onChange(fromStep, funnelsFilter?.funnel_to_step)
                }
            />
            <span className="text-muted-alt">to</span>
            <LemonSelect
                size="small"
                className="mx-1"
                dropdownMatchSelectWidth={false}
                optionTooltipPlacement="bottomLeft"
                disabled={!isFunnelWithEnoughSteps}
                options={optionsForRange(toRange)}
                value={funnelsFilter?.funnel_to_step || Math.max(numberOfSeries - 1, 1)}
                onChange={(toStep: number | null) =>
                    toStep != null && onChange(funnelsFilter?.funnel_from_step, toStep)
                }
            />
        </div>
    )
}
