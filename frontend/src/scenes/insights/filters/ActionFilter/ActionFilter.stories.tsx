import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { BindLogic, useMountedLogic, useValues } from 'kea'
import { useRef, useState } from 'react'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DISPLAY_TYPES_TO_CATEGORIES, SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { uuid } from 'lib/utils/dom'
import { alphabet } from 'lib/utils/strings'
import { insightLogic } from 'scenes/insights/insightLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { AnyEntityNode, NodeKind } from '~/queries/schema/schema-general'
import {
    ChartDisplayType,
    EntityTypes,
    FilterLogicalOperator,
    FilterType,
    InsightLogicProps,
    InsightType,
} from '~/types'

import __trendsLineBreakdown from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json'
import { ActionFilter, ActionFilterProps, SeriesActionFilter, SeriesActionFilterProps } from './ActionFilter'
import { MathAvailability } from './ActionFilterRow/types'
import { SeriesNode } from './seriesNode'

type Story = StoryObj<SeriesActionFilterProps>
const meta: Meta<SeriesActionFilterProps> = {
    title: 'Filters/Action Filter',
    decorators: [taxonomicFilterMocksDecorator],
}
export default meta

let uniqueNode = 0

const eventNode = (event: string, extra: Record<string, any> = {}): AnyEntityNode =>
    ({ kind: NodeKind.EventsNode, event, name: event, ...extra }) as AnyEntityNode

const group = (nodes: AnyEntityNode[], opts: { custom_name?: string; math?: Record<string, any> } = {}): SeriesNode =>
    ({
        kind: NodeKind.GroupNode,
        name: nodes.map((node) => node.name).join(', '),
        operator: FilterLogicalOperator.Or,
        nodes,
        ...opts.math,
        ...(opts.custom_name && { custom_name: opts.custom_name }),
    }) as SeriesNode

/** insightLogic only needs something cached to sit in; the editor reads its series from props. */
function useStoryInsightProps(): InsightLogicProps {
    const [dashboardItemId] = useState(() => `ActionFilterStory.${uniqueNode++}`)
    const insight = __trendsLineBreakdown as any
    return {
        dashboardItemId,
        doNotLoad: true,
        cachedInsight: { ...insight, short_id: dashboardItemId },
    } as InsightLogicProps
}

const DEFAULT_SERIES: SeriesNode[] = [
    eventNode('$pageview', {
        properties: [
            {
                key: '$browser',
                value: ['Chrome'],
                operator: 'exact',
                type: 'person',
            },
        ],
    }),
]

const renderActionFilter = ({ ...props }: Partial<SeriesActionFilterProps>): JSX.Element => {
    useMountedLogic(cohortsModel)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const id = useRef(uuid())
    const [series, setSeries] = useState<SeriesNode[]>(DEFAULT_SERIES)
    const [insightType] = useState<InsightType>(InsightType.TRENDS)
    const [display] = useState<ChartDisplayType>(ChartDisplayType.ActionsLineGraph)
    const insightProps = useStoryInsightProps()

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <SeriesActionFilter
                series={series}
                onChange={setSeries}
                typeKey={`trends_${id.current}`}
                insightType={insightType}
                trendsDisplayCategory={DISPLAY_TYPES_TO_CATEGORIES[display]}
                buttonCopy="Add graph series"
                showSeriesIndicator
                entitiesLimit={
                    insightType === InsightType.LIFECYCLE || SINGLE_SERIES_DISPLAY_TYPES.includes(display)
                        ? 1
                        : alphabet.length
                }
                mathAvailability={
                    insightType === InsightType.LIFECYCLE
                        ? MathAvailability.None
                        : insightType === InsightType.STICKINESS
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

const renderAutocaptureFilter = ({ ...props }: Partial<SeriesActionFilterProps>): JSX.Element => {
    useMountedLogic(cohortsModel)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const id = useRef(uuid())
    const [series, setSeries] = useState<SeriesNode[]>([
        eventNode('$autocapture', {
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
        }),
    ])
    const insightProps = useStoryInsightProps()

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <SeriesActionFilter
                series={series}
                onChange={setSeries}
                typeKey={`trends_${id.current}`}
                insightType={InsightType.TRENDS}
                trendsDisplayCategory={DISPLAY_TYPES_TO_CATEGORIES[ChartDisplayType.ActionsLineGraph]}
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

const renderGroupStory = (
    initialSeries: SeriesNode[],
    insightType: InsightType,
    actionFilterProps: Partial<SeriesActionFilterProps> = {}
) => {
    return ({ ...props }: Partial<SeriesActionFilterProps>): JSX.Element => {
        useMountedLogic(cohortsModel)
        const { groupsTaxonomicTypes } = useValues(groupsModel)
        const id = useRef(uuid())
        const [series, setSeries] = useState<SeriesNode[]>(initialSeries)
        const insightProps = useStoryInsightProps()

        return (
            <BindLogic logic={insightLogic} props={insightProps}>
                <SeriesActionFilter
                    {...props}
                    series={series}
                    onChange={setSeries}
                    typeKey={`group_story_${id.current}`}
                    insightType={insightType}
                    trendsDisplayCategory={
                        insightType === InsightType.TRENDS
                            ? DISPLAY_TYPES_TO_CATEGORIES[ChartDisplayType.ActionsLineGraph]
                            : null
                    }
                    buttonCopy={insightType === InsightType.FUNNELS ? 'Add funnel step' : 'Add graph series'}
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
    render: renderGroupStory([group([eventNode('$pageview'), eventNode('$exception')])], InsightType.TRENDS),
    args: {},
}

export const TrendsGroupCustomName: Story = {
    render: renderGroupStory(
        [group([eventNode('$pageview'), eventNode('$exception')], { custom_name: 'My custom name' })],
        InsightType.TRENDS
    ),
    args: {},
}

const hogqlMath = { math: 'hogql', math_hogql: 'sum(toInt(properties.$revenue))' }

export const TrendsGroupCustomNameHogQL: Story = {
    render: renderGroupStory(
        [
            group([eventNode('$pageview', hogqlMath)], {
                custom_name: 'My custom name (HogQL)',
                math: hogqlMath,
            }),
        ],
        InsightType.TRENDS
    ),
    args: {},
}

export const FunnelsGroupDefaultName: Story = {
    render: renderGroupStory(
        [group([eventNode('$pageview'), eventNode('$exception')]), eventNode('$pageleave') as SeriesNode],
        InsightType.FUNNELS,
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
        [
            group([eventNode('$pageview'), eventNode('$exception')], { custom_name: 'My custom name' }),
            eventNode('$pageleave') as SeriesNode,
        ],
        InsightType.FUNNELS,
        {
            seriesIndicatorType: 'numeric',
            sortable: true,
            mathAvailability: MathAvailability.FunnelsOnly,
        }
    ),
    args: {},
}

/**
 * The legacy-persisted surfaces (CDP, workflows, heatmaps, usage metrics, dashboard templates,
 * retention) keep the `filters`/`setFilters` props through the wrapper.
 */
const renderLegacyActionFilter = ({ ...props }: Partial<ActionFilterProps>): JSX.Element => {
    useMountedLogic(cohortsModel)
    const id = useRef(uuid())
    const [filters, setFilters] = useState<FilterType>({
        insight: InsightType.TRENDS,
        events: [
            {
                id: '$pageview',
                name: '$pageview',
                order: 0,
                type: EntityTypes.EVENTS,
                properties: [{ key: '$browser', value: ['Chrome'], operator: 'exact', type: 'person' }],
            },
        ],
    } as FilterType)
    const insightProps = useStoryInsightProps()

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <ActionFilter
                filters={filters}
                setFilters={(payload: FilterType) => setFilters({ ...filters, ...payload })}
                typeKey={`legacy_${id.current}`}
                buttonCopy="Add graph series"
                showSeriesIndicator
                mathAvailability={MathAvailability.None}
                {...props}
            />
        </BindLogic>
    )
}

export const LegacyFilters: Story = {
    render: renderLegacyActionFilter as any,
    args: {},
}
