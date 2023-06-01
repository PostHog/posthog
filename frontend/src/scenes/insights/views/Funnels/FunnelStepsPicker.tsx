import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { EntityFilter } from '~/types'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { FunnelsFilter } from '~/queries/schema'
import { LemonSelect, LemonSelectOptions, LemonSelectOption } from '@posthog/lemon-ui'

export function FunnelStepsPickerDataExploration(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { series, isFunnelWithEnoughSteps, funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const onChange = (funnel_from_step?: number, funnel_to_step?: number): void => {
        updateInsightFilter({ funnel_from_step, funnel_to_step })
    }

    return (
        <FunnelStepsPickerComponent
            filterSteps={series || []}
            numberOfSeries={series?.length || 0}
            isFunnelWithEnoughSteps={isFunnelWithEnoughSteps}
            funnelsFilter={funnelsFilter}
            onChange={onChange}
        />
    )
}

export function FunnelStepsPicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { filters, numberOfSeries, isFunnelWithEnoughSteps, filterSteps } = useValues(funnelLogic(insightProps))
    const { changeStepRange } = useActions(funnelLogic(insightProps))

    const onChange = (funnel_from_step?: number, funnel_to_step?: number): void => {
        changeStepRange(funnel_from_step, funnel_to_step)
    }

    return (
        <FunnelStepsPickerComponent
            filterSteps={filterSteps}
            numberOfSeries={numberOfSeries}
            isFunnelWithEnoughSteps={isFunnelWithEnoughSteps}
            funnelsFilter={filters}
            onChange={onChange}
        />
    )
}

type FunnelStepsPickerComponentProps = {
    filterSteps: Record<string, any>[]
    numberOfSeries: number
    isFunnelWithEnoughSteps: boolean
    funnelsFilter?: FunnelsFilter | null
    onChange: (funnel_from_step?: number, funnel_to_step?: number) => void
}

export function FunnelStepsPickerComponent({
    filterSteps,
    numberOfSeries,
    isFunnelWithEnoughSteps,
    funnelsFilter,
    onChange,
}: FunnelStepsPickerComponentProps): JSX.Element | null {
    const fromRange = isFunnelWithEnoughSteps ? Array.from(Array(Math.max(numberOfSeries)).keys()).slice(0, -1) : [0]
    const toRange = isFunnelWithEnoughSteps
        ? Array.from(Array(Math.max(numberOfSeries)).keys()).slice((funnelsFilter?.funnel_from_step ?? 0) + 1)
        : [1]

    const optionsForRange = (range: number[]): LemonSelectOptions<number> => {
        return range
            .map((stepIndex): LemonSelectOption<number> | null => {
                // data exploration has no order on series and instead relies on array order
                const stepFilter = filterSteps.find((f) => f.order === stepIndex) || filterSteps[stepIndex]
                return stepFilter
                    ? {
                          value: stepIndex,
                          label: `Step ${stepIndex + 1}`,
                          labelInMenu: (
                              <>
                                  <span>Step ${stepIndex + 1} – </span>
                                  <EntityFilterInfo filter={stepFilter as EntityFilter} />
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
