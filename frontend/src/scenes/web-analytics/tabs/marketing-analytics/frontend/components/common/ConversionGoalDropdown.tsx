import { useState } from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SeriesActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'
import { isEventsSeriesNode } from 'scenes/insights/filters/ActionFilter/seriesNode'

import { ConversionGoalFilter } from '~/queries/schema/schema-general'
import { conversionGoalPopoverFields } from '~/taxonomy/taxonomy'
import { BaseMathType, ChartDisplayCategory, PropertyMathType } from '~/types'

import { conversionGoalToSeries, seriesToConversionGoal } from '../../logic/utils'

interface ConversionGoalDropdownProps {
    value: ConversionGoalFilter
    onChange: (filter: ConversionGoalFilter) => void
    typeKey: string
    disabledReason?: string | null
}

export function ConversionGoalDropdown({
    value,
    onChange,
    typeKey,
    disabledReason,
}: ConversionGoalDropdownProps): JSX.Element {
    const [error, setError] = useState<string | null>(null)

    return (
        <div>
            <SeriesActionFilter
                bordered
                allowedMathTypes={[BaseMathType.TotalCount, BaseMathType.UniqueUsers, PropertyMathType.Sum]}
                series={conversionGoalToSeries(value)}
                trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
                mathAvailability={MathAvailability.All}
                onChange={(series) => {
                    // Check if user is trying to select "All Events"
                    if (isEventsSeriesNode(series[0]) && !series[0].event) {
                        setError('`All events` cannot be used as a conversion goal. Please select a specific event.')
                        return
                    }

                    // Clear any previous errors
                    setError(null)

                    const goal = seriesToConversionGoal(value, series)
                    if (goal) {
                        onChange(goal)
                    }
                }}
                typeKey={typeKey}
                showSeriesIndicator={false}
                entitiesLimit={1}
                showNumericalPropsOnly={true}
                hideRename={true}
                actionsTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.DataWarehouse,
                ]}
                dataWarehousePopoverFields={conversionGoalPopoverFields}
                excludedProperties={{
                    [TaxonomicFilterGroupType.Events]: [null],
                }}
                disabled={!!disabledReason}
            />
            {error && <div className="text-danger mt-2 text-sm">{error}</div>}
        </div>
    )
}
