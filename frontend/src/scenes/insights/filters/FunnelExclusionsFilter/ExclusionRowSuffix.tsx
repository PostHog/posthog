import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconDelete } from 'lib/lemon-ui/icons'
import { getClampedStepRange } from 'scenes/funnels/funnelUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { FunnelsFilter, FunnelsQuery } from '~/queries/schema'
import { ActionFilter as ActionFilterType, FunnelExclusion } from '~/types'

type ExclusionRowSuffixComponentBaseProps = {
    filter: ActionFilterType | FunnelExclusion
    index: number
    onClose?: () => void
    isVertical: boolean
}

export function ExclusionRowSuffix({
    filter,
    index,
    onClose,
    isVertical,
}: ExclusionRowSuffixComponentBaseProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource, insightFilter, series, isFunnelWithEnoughSteps, exclusionDefaultStepRange } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const setOneEventExclusionFilter = (eventFilter: FunnelExclusion, index: number): void => {
        const exclusions = ((insightFilter as FunnelsFilter)?.exclusions || []).map((e, e_i) =>
            e_i === index
                ? getClampedStepRange({
                      stepRange: eventFilter,
                      query: querySource as FunnelsQuery,
                  })
                : e
        )

        updateInsightFilter({
            exclusions,
        })
    }

    const exclusions = (insightFilter as FunnelsFilter)?.exclusions
    const numberOfSeries = series?.length || 0

    const stepRange = {
        funnelFromStep: exclusions?.[index]?.funnelFromStep ?? exclusionDefaultStepRange.funnelFromStep,
        funnelToStep: exclusions?.[index]?.funnelToStep ?? exclusionDefaultStepRange.funnelToStep,
    }

    const onChange = (
        funnelFromStep: number | undefined = stepRange.funnelFromStep,
        funnelToStep: number | undefined = stepRange.funnelToStep
    ): void => {
        setOneEventExclusionFilter(
            {
                ...filter,
                funnelFromStep,
                funnelToStep,
            },
            index
        )
    }

    return (
        <div className={clsx('flex items-center flex-nowrap pl-1 mx-0', isVertical ? 'w-full my-1' : 'w-auto my-0')}>
            between
            <LemonSelect
                className="mx-1"
                size="small"
                value={stepRange.funnelFromStep || 0}
                onChange={onChange}
                options={Array.from(Array(numberOfSeries).keys())
                    .slice(0, -1)
                    .map((stepIndex) => ({ value: stepIndex, label: `Step ${stepIndex + 1}` }))}
                disabled={!isFunnelWithEnoughSteps}
            />
            and
            <LemonSelect
                className="ml-1"
                size="small"
                value={stepRange.funnelToStep || (stepRange.funnelFromStep ?? 0) + 1}
                onChange={(toStep: number) => onChange(stepRange.funnelFromStep, toStep)}
                options={Array.from(Array(numberOfSeries).keys())
                    .slice((stepRange.funnelFromStep ?? 0) + 1)
                    .map((stepIndex) => ({ value: stepIndex, label: `Step ${stepIndex + 1}` }))}
                disabled={!isFunnelWithEnoughSteps}
            />
            <LemonButton
                icon={<IconDelete />}
                onClick={onClose}
                data-attr="delete-prop-exclusion-filter"
                title="Delete event exclusion series"
            />
        </div>
    )
}
