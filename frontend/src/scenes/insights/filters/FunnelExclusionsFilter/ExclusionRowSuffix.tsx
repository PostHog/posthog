import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { getClampedExclusionStepRange } from 'scenes/funnels/funnelUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { FunnelsQuery } from '~/queries/schema'

type ExclusionRowSuffixComponentBaseProps = {
    index: number
    onClose?: () => void
    isVertical: boolean
}

export function ExclusionRowSuffix({
    index,
    onClose,
    isVertical,
}: ExclusionRowSuffixComponentBaseProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource, funnelsFilter, series, isFunnelWithEnoughSteps, exclusionDefaultStepRange } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const exclusions = funnelsFilter?.exclusions
    const numberOfSeries = series?.length || 0

    const stepRange = {
        funnelFromStep: exclusions?.[index]?.funnelFromStep ?? exclusionDefaultStepRange.funnelFromStep,
        funnelToStep: exclusions?.[index]?.funnelToStep ?? exclusionDefaultStepRange.funnelToStep,
    }

    const onChange = (funnelFromStep = stepRange.funnelFromStep, funnelToStep = stepRange.funnelToStep): void => {
        const newStepRange = getClampedExclusionStepRange({
            stepRange: { funnelFromStep, funnelToStep },
            query: querySource as FunnelsQuery,
        })
        const newExclusions = funnelsFilter?.exclusions?.map((exclusion, exclusionIndex) =>
            exclusionIndex === index ? { ...exclusion, ...newStepRange } : exclusion
        )
        updateInsightFilter({ exclusions: newExclusions })
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
                size="small"
                icon={<IconTrash />}
                onClick={onClose}
                data-attr="delete-prop-exclusion-filter"
                title="Delete event exclusion series"
                className="ml-1"
            />
        </div>
    )
}
