import { useActions, useValues } from 'kea'

import { IconFilter, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { IconWithCount } from 'lib/lemon-ui/icons'
import { getClampedFunnelStepRange } from 'scenes/funnels/funnelUtils'
import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

type ExclusionRowSuffixComponentBaseProps = {
    index: number
    onClose?: () => void
    typeKey: string
}

export function ExclusionRowSuffix({
    index,
    onClose,
    typeKey,
}: ExclusionRowSuffixComponentBaseProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter, series, isFunnelWithEnoughSteps, exclusionDefaultStepRange } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    // Get the entity filter logic that was created by the parent ActionFilter component
    const mountedLogic = entityFilterLogic.findMounted({ typeKey })

    // Use the logic for visibility state if it exists, otherwise use local state
    const propertyFiltersVisible = (mountedLogic && mountedLogic.values.entityFilterVisible[index]) || false

    const exclusions = funnelsFilter?.exclusions
    const numberOfSeries = series?.length || 0

    const stepRange = {
        funnelFromStep: exclusions?.[index]?.funnelFromStep ?? exclusionDefaultStepRange.funnelFromStep,
        funnelToStep: exclusions?.[index]?.funnelToStep ?? exclusionDefaultStepRange.funnelToStep,
    }

    const onChange = (funnelFromStep = stepRange.funnelFromStep, funnelToStep = stepRange.funnelToStep): void => {
        const newStepRange = getClampedFunnelStepRange({ funnelFromStep, funnelToStep }, series)
        const newExclusions = funnelsFilter?.exclusions?.map((exclusion, exclusionIndex) =>
            exclusionIndex === index ? { ...exclusion, ...newStepRange } : exclusion
        )
        updateInsightFilter({ exclusions: newExclusions })
    }

    const togglePropertyFiltersVisibility = (): void => {
        if (mountedLogic) {
            mountedLogic.actions.setEntityFilterVisibility(index, !propertyFiltersVisible)
        }
    }

    const propertyFiltersButton = (
        <IconWithCount key="property-filter" count={exclusions?.[index]?.properties?.length || 0} showZero={false}>
            <LemonButton
                icon={<IconFilter />}
                title="Show filters"
                data-attr={`show-prop-filter-${index}`}
                noPadding
                onClick={togglePropertyFiltersVisibility}
            />
        </IconWithCount>
    )

    return (
        <div className="flex items-center gap-2 w-full p-1 my-1">
            <span>between</span>
            <LemonSelect
                className="min-w-0 flex-shrink"
                size="small"
                value={stepRange.funnelFromStep || 0}
                onChange={onChange}
                options={Array.from(Array(numberOfSeries).keys())
                    .slice(0, -1)
                    .map((stepIndex) => ({ value: stepIndex, label: `Step ${stepIndex + 1}` }))}
                disabled={!isFunnelWithEnoughSteps}
            />
            <span>and</span>
            <LemonSelect
                className="min-w-0 flex-shrink"
                size="small"
                value={stepRange.funnelToStep || (stepRange.funnelFromStep ?? 0) + 1}
                onChange={(toStep: number) => onChange(stepRange.funnelFromStep, toStep)}
                options={Array.from(Array(numberOfSeries).keys())
                    .slice((stepRange.funnelFromStep ?? 0) + 1)
                    .map((stepIndex) => ({ value: stepIndex, label: `Step ${stepIndex + 1}` }))}
                disabled={!isFunnelWithEnoughSteps}
            />
            <div className="flex items-center gap-1 ml-auto">
                {propertyFiltersButton}
                <LemonButton
                    size="small"
                    icon={<IconTrash />}
                    onClick={onClose}
                    data-attr="delete-prop-exclusion-filter"
                    title="Delete event exclusion series"
                    noPadding
                />
            </div>
        </div>
    )
}
