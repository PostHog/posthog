import { useRef, useState } from 'react'
import { ActionFilter, ActionFilterProps } from './ActionFilter'
import { cohortsModel } from '~/models/cohortsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { useMountedLogic, useValues } from 'kea'
import { FilterType, InsightType } from '~/types'
import { MathAvailability } from './ActionFilterRow/ActionFilterRow'
import { groupsModel } from '~/models/groupsModel'
import { alphabet, uuid } from 'lib/utils'
import { ComponentStory } from '@storybook/react'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { isFilterWithDisplay, isLifecycleFilter } from 'scenes/insights/sharedUtils'

export default {
    title: 'Filters/Action Filter',
    decorators: [taxonomicFilterMocksDecorator],
}

const Template: ComponentStory<typeof ActionFilter> = ({ ...props }: Partial<ActionFilterProps>) => {
    useMountedLogic(cohortsModel)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const id = useRef(uuid())

    const [filters, setFilters] = useState<FilterType>({
        insight: InsightType.TRENDS,
        events: [
            {
                id: '$pageview',
                name: '$pageview',
                order: 0,
                type: 'events',
                properties: [
                    {
                        key: '$browser',
                        value: ['Chrome'],
                        operator: 'exact',
                        type: 'person',
                    },
                ],
            },
        ],
    })

    return (
        <ActionFilter
            filters={filters}
            setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
            typeKey={`trends_${id.current}`}
            buttonCopy="Add graph series"
            showSeriesIndicator
            entitiesLimit={
                isLifecycleFilter(filters) ||
                (isFilterWithDisplay(filters) &&
                    filters.display &&
                    SINGLE_SERIES_DISPLAY_TYPES.includes(filters.display))
                    ? 1
                    : alphabet.length
            }
            mathAvailability={
                filters.insight === InsightType.LIFECYCLE
                    ? MathAvailability.None
                    : filters.insight === InsightType.STICKINESS
                    ? MathAvailability.ActorsOnly
                    : MathAvailability.All
            }
            propertiesTaxonomicGroupTypes={[
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.EventFeatureFlags,
                ...groupsTaxonomicTypes,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.Elements,
                TaxonomicFilterGroupType.HogQLExpression,
            ]}
            {...props}
        />
    )
}

export const Standard = Template.bind({})
Standard.args = {}

export const Bordered = Template.bind({})
Bordered.args = {
    bordered: true,
}

export const PropertyFiltersWithPopover = Template.bind({})
PropertyFiltersWithPopover.args = {
    propertyFiltersPopover: true,
}

export const Sortable = Template.bind({})
Sortable.args = {
    sortable: true,
}

export const FunnelLike = Template.bind({})
FunnelLike.args = {
    sortable: true,
    bordered: true,
    seriesIndicatorType: 'numeric',
}

export const SingleFilter = Template.bind({})
SingleFilter.args = {
    entitiesLimit: 1,
}
