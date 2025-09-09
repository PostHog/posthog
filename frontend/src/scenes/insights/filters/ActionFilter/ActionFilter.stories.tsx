import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { BindLogic, useMountedLogic, useValues } from 'kea'
import { useRef, useState } from 'react'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { alphabet, uuid } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isFilterWithDisplay, isLifecycleFilter } from 'scenes/insights/sharedUtils'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { FilterType, InsightLogicProps, InsightType } from '~/types'

import { ActionFilter, ActionFilterProps } from './ActionFilter'
import { MathAvailability } from './ActionFilterRow/ActionFilterRow'

type Story = StoryObj<typeof ActionFilter>
const meta: Meta<typeof ActionFilter> = {
    title: 'Filters/Action Filter',
    decorators: [taxonomicFilterMocksDecorator],
}
export default meta

let uniqueNode = 0

const Template: StoryFn<typeof ActionFilter> = ({ ...props }: Partial<ActionFilterProps>) => {
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

    const [dashboardItemId] = useState(() => `ActionFilterStory.${uniqueNode++}`)

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const insight = require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json')
    const cachedInsight = { ...insight, short_id: dashboardItemId, filters }
    const insightProps = { dashboardItemId, doNotLoad: true, cachedInsight } as InsightLogicProps

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
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
        </BindLogic>
    )
}

export const Standard: Story = Template.bind({})
Standard.args = {}

export const Bordered: Story = Template.bind({})
Bordered.args = {
    bordered: true,
}

export const PropertyFiltersWithPopover: Story = Template.bind({})
PropertyFiltersWithPopover.args = {
    propertyFiltersPopover: true,
}

export const Sortable: Story = Template.bind({})
Sortable.args = {
    sortable: true,
}

export const FunnelLike: Story = Template.bind({})
FunnelLike.args = {
    sortable: true,
    bordered: true,
    seriesIndicatorType: 'numeric',
}

export const SingleFilter: Story = Template.bind({})
SingleFilter.args = {
    entitiesLimit: 1,
}
