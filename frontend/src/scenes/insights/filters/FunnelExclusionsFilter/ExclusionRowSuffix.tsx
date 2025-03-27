import { IconFilter, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconWithCount } from 'lib/lemon-ui/icons'
import React from 'react'
import { getClampedExclusionStepRange } from 'scenes/funnels/funnelUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { FunnelsQuery } from '~/queries/schema/schema-general'
import { AnyPropertyFilter } from '~/types'

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

    const handlePropertyFiltersChange = (properties: AnyPropertyFilter[]): void => {
        const newExclusions = funnelsFilter?.exclusions?.map((exclusion, exclusionIndex) =>
            exclusionIndex === index ? { ...exclusion, properties } : exclusion
        )
        updateInsightFilter({ exclusions: newExclusions })
    }

    const [propertyFiltersVisible, setPropertyFiltersVisible] = React.useState(false)

    const propertyFiltersButton = (
        <IconWithCount key="property-filter" count={exclusions?.[index]?.properties?.length || 0} showZero={false}>
            <LemonButton
                icon={<IconFilter />}
                title="Show filters"
                data-attr={`show-prop-filter-${index}`}
                noPadding
                onClick={() => setPropertyFiltersVisible(!propertyFiltersVisible)}
            />
        </IconWithCount>
    )

    return (
        <div
            className={clsx(
                'flex flex-col gap-2 items-start flex-nowrap pl-1 mx-0 bg-bg-light rounded p-2 w-full',
                isVertical ? 'my-1' : 'my-0'
            )}
        >
            <div className="flex items-center gap-2 w-full">
                <div className="flex items-center">
                    <span>between</span>
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
                    <span>and</span>
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
                </div>
                <div className="flex-1" />
                <div className="flex items-center gap-2">
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
            {propertyFiltersVisible && (
                <div className="w-full mt-2">
                    <PropertyFilters
                        pageKey={`funnel-exclusion-${index}`}
                        propertyFilters={exclusions?.[index]?.properties ?? []}
                        onChange={handlePropertyFiltersChange}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            TaxonomicFilterGroupType.EventFeatureFlags,
                            TaxonomicFilterGroupType.NumericalEventProperties,
                        ]}
                    />
                </div>
            )}
        </div>
    )
}
