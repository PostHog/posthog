import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { PROPERTY_MATH_DEFINITIONS } from 'scenes/trends/mathsLogic'

import { PropertyMathType } from '~/types'

export function RetentionAggregationSelector(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const aggregationType = retentionFilter?.aggregationType || 'count'
    const aggregationProperty = retentionFilter?.aggregationProperty
    const isPropertyValueAggregation = aggregationType === 'sum' || aggregationType === 'avg'

    // Local state to track which property math type to show in the dropdown label
    // This mirrors the behavior in Trends where the "Property value" option remembers the last selected math type
    const [propertyMathTypeShown, setPropertyMathTypeShown] = useState<PropertyMathType.Average | PropertyMathType.Sum>(
        aggregationType === 'sum'
            ? PropertyMathType.Sum
            : aggregationType === 'avg'
              ? PropertyMathType.Average
              : PropertyMathType.Average
    )

    useEffect(() => {
        if (aggregationType === 'sum') {
            setPropertyMathTypeShown(PropertyMathType.Sum)
        } else if (aggregationType === 'avg') {
            setPropertyMathTypeShown(PropertyMathType.Average)
        }
    }, [aggregationType])

    const options: LemonSelectOption<string>[] = [
        {
            value: 'count',
            label: 'Retention rate',
            tooltip: 'The percentage of users who return in the specific interval.',
        },
        {
            // The "Property value" option acts as a container for the nested selector
            value: propertyMathTypeShown,
            label: `Property value ${PROPERTY_MATH_DEFINITIONS[propertyMathTypeShown].shortName}`,
            tooltip: 'Statistical analysis of property value (Sum or Average).',
            labelInMenu: (
                <div className="flex items-center gap-2">
                    <span>Property value</span>
                    <LemonSelect
                        value={propertyMathTypeShown}
                        onSelect={(value) => {
                            const newType = value as PropertyMathType.Average | PropertyMathType.Sum
                            setPropertyMathTypeShown(newType)
                            // Map PropertyMathType to aggregationType
                            const aggregationType = newType === PropertyMathType.Sum ? 'sum' : 'avg'
                            updateInsightFilter({ aggregationType })
                        }}
                        options={[
                            {
                                value: PropertyMathType.Average,
                                label: PROPERTY_MATH_DEFINITIONS[PropertyMathType.Average].shortName,
                                tooltip: PROPERTY_MATH_DEFINITIONS[PropertyMathType.Average].description,
                            },
                            {
                                value: PropertyMathType.Sum,
                                label: PROPERTY_MATH_DEFINITIONS[PropertyMathType.Sum].shortName,
                                tooltip: PROPERTY_MATH_DEFINITIONS[PropertyMathType.Sum].description,
                            },
                        ]}
                        onClick={(e) => e.stopPropagation()}
                        size="small"
                        dropdownMatchSelectWidth={false}
                        optionTooltipPlacement="right"
                    />
                </div>
            ),
        },
    ]

    return (
        <div className="flex items-center gap-2">
            <LemonSelect
                value={aggregationType === 'count' ? 'count' : propertyMathTypeShown}
                onChange={(val) => {
                    if (val === 'count') {
                        updateInsightFilter({ aggregationType: 'count', aggregationProperty: undefined })
                    } else {
                        // If switching to property value, use the currently "shown" type (avg or sum)
                        const aggregationType = propertyMathTypeShown === PropertyMathType.Sum ? 'sum' : 'avg'
                        updateInsightFilter({ aggregationType })
                    }
                }}
                options={options}
                size="small"
                dropdownMatchSelectWidth={false}
                optionTooltipPlacement="right"
                data-attr="retention-aggregation-type-selector"
            />

            {isPropertyValueAggregation && (
                <TaxonomicStringPopover
                    groupType={TaxonomicFilterGroupType.NumericalEventProperties}
                    groupTypes={[TaxonomicFilterGroupType.NumericalEventProperties]}
                    value={aggregationProperty}
                    onChange={(val) => updateInsightFilter({ aggregationProperty: val })}
                    placeholder="Select property"
                    data-attr="retention-aggregation-property-selector"
                    renderValue={(currentValue) => (
                        <Tooltip
                            title={
                                <>
                                    Calculate{' '}
                                    {aggregationType === 'sum'
                                        ? PROPERTY_MATH_DEFINITIONS[PropertyMathType.Sum].name.toLowerCase()
                                        : PROPERTY_MATH_DEFINITIONS[PropertyMathType.Average].name.toLowerCase()}{' '}
                                    from property <code>{currentValue}</code>.
                                    <br />
                                    Note that only events where <code>{currentValue}</code> is set with a numeric value
                                    will be taken into account.
                                </>
                            }
                            placement="right"
                        >
                            <PropertyKeyInfo
                                value={currentValue}
                                disablePopover
                                type={TaxonomicFilterGroupType.EventProperties}
                            />
                        </Tooltip>
                    )}
                />
            )}
        </div>
    )
}
