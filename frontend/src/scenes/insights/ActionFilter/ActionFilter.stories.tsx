import React, { useState } from 'react'
import { ActionFilter, ActionFilterProps } from './ActionFilter'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { cohortsModel } from '~/models/cohortsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { useMountedLogic, useValues } from 'kea'
import { ChartDisplayType, FilterType, InsightType } from '~/types'
import { MathAvailability } from './ActionFilterRow/ActionFilterRow'
import { groupsModel } from '~/models/groupsModel'
import { alphabet } from 'lib/utils'
import { ComponentStory } from '@storybook/react'

export default {
    title: 'Filters/Action Filter',
    decorators: [taxonomicFilterMocksDecorator],
}

const Template: ComponentStory<typeof ActionFilter> = ({ ...props }: Partial<ActionFilterProps>) => {
    useMountedLogic(personPropertiesModel)
    useMountedLogic(cohortsModel)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const [filters, setFilters] = useState<FilterType>({
        insight: InsightType.TRENDS,
        events: [
            {
                id: '$pageview',
                name: '$pageview',
                order: 0,
                type: 'events',
            },
        ],
    })

    return (
        <ActionFilter
            filters={filters}
            setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
            typeKey={`trends_${InsightType.TRENDS}`}
            buttonCopy="Add graph series"
            buttonType="link"
            showSeriesIndicator
            entitiesLimit={
                filters.insight === InsightType.LIFECYCLE || filters.display === ChartDisplayType.WorldMap
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
                ...groupsTaxonomicTypes,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.Elements,
            ]}
            customRowPrefix={undefined}
            {...props}
        />
    )
}

export const Standard = Template.bind({})
Standard.args = {}

export const FullWidth = Template.bind({})
FullWidth.args = {
    fullWidth: true,
}

export const HorizontalUI = Template.bind({})
HorizontalUI.args = {
    horizontalUI: true,
}
