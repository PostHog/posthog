import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
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
import { EntityTypes, FilterLogicalOperator, FilterType, InsightLogicProps, InsightType } from '~/types'

import { ActionFilter, ActionFilterProps } from './ActionFilter'
import { MathAvailability } from './ActionFilterRow/ActionFilterRow'

type Story = StoryObj<ActionFilterProps>
const meta: Meta<ActionFilterProps> = {
    title: 'Filters/Action Filter',
    decorators: [taxonomicFilterMocksDecorator],
}
export default meta

let uniqueNode = 0

const renderActionFilter = ({ ...props }: Partial<ActionFilterProps>): JSX.Element => {
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

export const Standard: Story = {
    render: renderActionFilter,
    args: {},
}

export const Bordered: Story = {
    render: renderActionFilter,
    args: {
        bordered: true,
    },
}

export const PropertyFiltersWithPopover: Story = {
    render: renderActionFilter,
    args: {
        propertyFiltersPopover: true,
    },
}

export const Sortable: Story = {
    render: renderActionFilter,
    args: {
        sortable: true,
    },
}

export const FunnelLike: Story = {
    render: renderActionFilter,
    args: {
        sortable: true,
        bordered: true,
        seriesIndicatorType: 'numeric',
    },
}

export const SingleFilter: Story = {
    render: renderActionFilter,
    args: {
        entitiesLimit: 1,
    },
}

const renderAutocaptureFilter = ({ ...props }: Partial<ActionFilterProps>): JSX.Element => {
    useMountedLogic(cohortsModel)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const id = useRef(uuid())

    const [filters, setFilters] = useState<FilterType>({
        insight: InsightType.TRENDS,
        events: [
            {
                id: '$autocapture',
                name: '$autocapture',
                order: 0,
                type: 'events',
                properties: [
                    {
                        key: '$el_text',
                        value: 'Submit',
                        operator: 'exact',
                        type: 'event',
                    },
                    {
                        key: 'selector',
                        value: '.btn-primary',
                        operator: 'exact',
                        type: 'element',
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
                mathAvailability={MathAvailability.All}
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

export const AutocaptureWithSaveAsAction: Story = {
    render: renderAutocaptureFilter,
    args: {},
    parameters: {
        testOptions: { waitForSelector: '[data-attr="autocapture-save-as-action"]' },
    },
    play: async ({ canvasElement }) => {
        const filterToggle = await waitFor(
            () => {
                const button = canvasElement.querySelector<HTMLElement>('[data-attr="show-prop-filter-0"]')
                if (!button) {
                    throw new Error('Filters button not yet rendered')
                }
                return button
            },
            { timeout: 2000 }
        )
        await userEvent.click(filterToggle)
    },
}

const groupEvent = (id: string, name: string, order: number, math?: Record<string, any>): Record<string, any> => ({
    id,
    type: EntityTypes.EVENTS,
    name,
    order,
    ...math,
})

const group = (
    order: number,
    nestedFilters: any[],
    opts: { custom_name?: string; math?: Record<string, any> } = {}
): Record<string, any> => ({
    id: null,
    type: EntityTypes.GROUPS,
    name: nestedFilters.map((f: any) => f.name).join(', '),
    order,
    operator: FilterLogicalOperator.Or,
    nestedFilters,
    ...opts.math,
    ...(opts.custom_name && { custom_name: opts.custom_name }),
})

const renderGroupStory = (initialFilters: FilterType, actionFilterProps: Partial<ActionFilterProps> = {}) => {
    return ({ ...props }: Partial<ActionFilterProps>): JSX.Element => {
        useMountedLogic(cohortsModel)
        const { groupsTaxonomicTypes } = useValues(groupsModel)
        const id = useRef(uuid())
        const [filters, setFilters] = useState<FilterType>(initialFilters)
        const [dashboardItemId] = useState(() => `ActionFilterStory.${uniqueNode++}`)

        // eslint-disable-next-line @typescript-eslint/no-var-requires
        const insight = require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json')
        const cachedInsight = { ...insight, short_id: dashboardItemId, filters }
        const insightProps = { dashboardItemId, doNotLoad: true, cachedInsight } as InsightLogicProps

        return (
            <BindLogic logic={insightLogic} props={insightProps}>
                <ActionFilter
                    {...props}
                    filters={filters}
                    setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                    typeKey={`group_story_${id.current}`}
                    buttonCopy={filters.insight === InsightType.FUNNELS ? 'Add funnel step' : 'Add graph series'}
                    showSeriesIndicator
                    entitiesLimit={alphabet.length}
                    propertiesTaxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        ...groupsTaxonomicTypes,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.HogQLExpression,
                    ]}
                    {...actionFilterProps}
                />
            </BindLogic>
        )
    }
}

export const TrendsGroupDefaultName: Story = {
    render: renderGroupStory({
        insight: InsightType.TRENDS,
        groups: [group(0, [groupEvent('$pageview', '$pageview', 0), groupEvent('$exception', '$exception', 1)])],
    }),
    args: {},
}

export const TrendsGroupCustomName: Story = {
    render: renderGroupStory({
        insight: InsightType.TRENDS,
        groups: [
            group(0, [groupEvent('$pageview', '$pageview', 0), groupEvent('$exception', '$exception', 1)], {
                custom_name: 'My custom name',
            }),
        ],
    }),
    args: {},
}

const hogqlMath = { math: 'hogql', math_hogql: 'sum(toInt(properties.$revenue))' }

export const TrendsGroupCustomNameHogQL: Story = {
    render: renderGroupStory({
        insight: InsightType.TRENDS,
        groups: [
            group(0, [groupEvent('$pageview', '$pageview', 0, hogqlMath)], {
                custom_name: 'My custom name (HogQL)',
                math: hogqlMath,
            }),
        ],
    }),
    args: {},
}

export const FunnelsGroupDefaultName: Story = {
    render: renderGroupStory(
        {
            insight: InsightType.FUNNELS,
            groups: [group(0, [groupEvent('$pageview', '$pageview', 0), groupEvent('$exception', '$exception', 1)])],
            events: [groupEvent('$pageleave', '$pageleave', 1)],
        },
        {
            seriesIndicatorType: 'numeric',
            sortable: true,
            mathAvailability: MathAvailability.FunnelsOnly,
        }
    ),
    args: {},
}

export const FunnelsGroupCustomName: Story = {
    render: renderGroupStory(
        {
            insight: InsightType.FUNNELS,
            groups: [
                group(0, [groupEvent('$pageview', '$pageview', 0), groupEvent('$exception', '$exception', 1)], {
                    custom_name: 'My custom name',
                }),
            ],
            events: [groupEvent('$pageleave', '$pageleave', 1)],
        },
        {
            seriesIndicatorType: 'numeric',
            sortable: true,
            mathAvailability: MathAvailability.FunnelsOnly,
        }
    ),
    args: {},
}
