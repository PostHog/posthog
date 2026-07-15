import type { Meta, StoryObj } from '@storybook/react'

import { DashboardFilter, TileFilters } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator, QueryBasedInsightModel } from '~/types'

import __dataTableEvents from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableEvents.json'
import __dataTableHogQL from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json'
import __dataVisualizationHogQL from '../../../../mocks/fixtures/api/projects/team_id/insights/dataVisualizationHogQL.json'
import __funnelLeftToRight from '../../../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'
import __lifecycle from '../../../../mocks/fixtures/api/projects/team_id/insights/lifecycle.json'
import __retention from '../../../../mocks/fixtures/api/projects/team_id/insights/retention.json'
import __stickiness from '../../../../mocks/fixtures/api/projects/team_id/insights/stickiness.json'
import __trendsFormulas from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsFormulas.json'
import __trendsLine from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import __trendsLineMulti from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'
import __trendsPie from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'
import __trendsTable from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json'
import __trendsValue from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'
import __trendsWorldMap from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'
import __userPaths from '../../../../mocks/fixtures/api/projects/team_id/insights/userPaths.json'
import { InsightDetails as InsightDetailsComponent } from './InsightDetails'

interface StoryArgs {
    insight: QueryBasedInsightModel
    filtersOverride?: DashboardFilter
    tileFiltersOverride?: TileFilters | null
}

function withOwnProperties(properties: AnyPropertyFilter[]): QueryBasedInsightModel {
    const insight = structuredClone(__trendsLine) as any
    insight.query.source.properties = properties
    return insight
}

type Story = StoryObj<StoryArgs>
const meta: Meta<StoryArgs> = {
    title: 'Components/Cards/Insight Details',
    component: InsightDetailsComponent as any,
    parameters: {
        mockDate: '2025-12-10',
    },
    render: ({ insight, filtersOverride, tileFiltersOverride }) => {
        return (
            <div className="bg-surface-primary w-[24rem] p-4 rounded">
                <InsightDetailsComponent
                    query={insight.query}
                    footerInfo={insight}
                    filtersOverride={filtersOverride}
                    tileFiltersOverride={tileFiltersOverride}
                />
            </div>
        )
    },
}
export default meta

export const Trends: Story = {
    args: {
        insight: __trendsLine as any,
    },
}

export const TrendsMulti: Story = {
    args: {
        insight: __trendsLineMulti as any,
    },
}

export const TrendsHorizontalBar: Story = {
    args: {
        insight: __trendsValue as any,
    },
}

export const TrendsTable: Story = {
    args: { insight: __trendsTable as any },
}

export const TrendsPie: Story = {
    args: { insight: __trendsPie as any },
}

export const TrendsWorldMap: Story = {
    args: {
        insight: __trendsWorldMap as any,
    },
}

export const TrendsFormulas: Story = {
    args: {
        insight: __trendsFormulas as any,
    },
}

export const Funnel: Story = {
    args: {
        insight: __funnelLeftToRight as any,
    },
}

export const Retention: Story = {
    args: {
        insight: __retention as any,
    },
}

export const Paths: Story = {
    args: {
        insight: __userPaths as any,
    },
}

export const Stickiness: Story = {
    args: { insight: __stickiness as any },
}

export const Lifecycle: Story = {
    args: {
        insight: __lifecycle as any,
    },
}

export const DataTableHogQLQuery: Story = {
    args: {
        insight: __dataTableHogQL as any,
    },
}

export const DataVisualizationHogQLQuery: Story = {
    args: {
        insight: __dataVisualizationHogQL as any,
    },
}

export const DataTableEventsQuery: Story = {
    args: {
        insight: __dataTableEvents as any,
    },
}

export const DashboardFilterOverrides: Story = {
    args: {
        insight: __trendsLine as any,
        filtersOverride: {
            date_from: '-30d',
            properties: [
                {
                    type: PropertyFilterType.Event,
                    key: '$browser',
                    operator: PropertyOperator.Exact,
                    value: ['Chrome'],
                },
            ],
            breakdown_filter: { breakdown: '$os', breakdown_type: 'event' },
        },
    },
}

export const TileFilterOverrides: Story = {
    args: {
        insight: __trendsLine as any,
        tileFiltersOverride: {
            date_from: '-7d',
            properties: [
                {
                    type: PropertyFilterType.Event,
                    key: '$geoip_country_name',
                    operator: PropertyOperator.Exact,
                    value: ['United States'],
                },
            ],
        },
    },
}

export const MergedFilterOverrides: Story = {
    args: {
        insight: __trendsLine as any,
        filtersOverride: {
            date_from: '-30d',
            breakdown_filter: { breakdown: '$os', breakdown_type: 'event' },
        },
        tileFiltersOverride: {
            breakdown_filter: { breakdown: '$browser', breakdown_type: 'event' },
        },
    },
}

export const TileDateOverridesDashboard: Story = {
    args: {
        insight: __trendsLine as any,
        filtersOverride: {
            date_from: '-30d',
        },
        tileFiltersOverride: {
            date_from: '-7d',
        },
    },
}

export const TilePropertyOverridesDashboard: Story = {
    args: {
        insight: __trendsLine as any,
        filtersOverride: {
            properties: [
                {
                    type: PropertyFilterType.Event,
                    key: '$browser',
                    operator: PropertyOperator.Exact,
                    value: ['Safari'],
                },
            ],
        },
        tileFiltersOverride: {
            properties: [
                {
                    type: PropertyFilterType.Event,
                    key: '$browser',
                    operator: PropertyOperator.Exact,
                    value: ['Firefox'],
                },
            ],
        },
    },
}

const PROPERTY_FILTER_CONFLICT_CASES: {
    title: string
    insightProperties: AnyPropertyFilter[]
    dashboardProperties: AnyPropertyFilter[]
}[] = [
    {
        title: 'Same value on both layers — duplicate, not a conflict',
        insightProperties: [
            { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: ['Chrome'] },
        ],
        dashboardProperties: [
            { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: ['Chrome'] },
        ],
    },
    {
        title: 'Overlapping exact sets — compatible, both apply',
        insightProperties: [
            {
                type: PropertyFilterType.Event,
                key: '$browser',
                operator: PropertyOperator.Exact,
                value: ['Chrome', 'Safari'],
            },
        ],
        dashboardProperties: [
            { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: ['Chrome'] },
        ],
    },
    {
        title: 'Disjoint exact sets — contradicts, dashboard wins',
        insightProperties: [
            { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: ['Firefox'] },
        ],
        dashboardProperties: [
            { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: ['Chrome'] },
        ],
    },
    {
        title: "utm_source = google + is_set — stacks (Andy's original case from PR #70139)",
        insightProperties: [
            { type: PropertyFilterType.Event, key: 'utm_source', operator: PropertyOperator.Exact, value: ['google'] },
        ],
        dashboardProperties: [{ type: PropertyFilterType.Event, key: 'utm_source', operator: PropertyOperator.IsSet }],
    },
    {
        title: 'is_not_set vs is_set — contradicts, no value can satisfy both',
        insightProperties: [{ type: PropertyFilterType.Event, key: 'utm_source', operator: PropertyOperator.IsNotSet }],
        dashboardProperties: [{ type: PropertyFilterType.Event, key: 'utm_source', operator: PropertyOperator.IsSet }],
    },
    {
        title: 'is_not vs is_not_set — compatible (a negated filter also matches unset)',
        insightProperties: [
            { type: PropertyFilterType.Event, key: '$os', operator: PropertyOperator.IsNot, value: ['Windows'] },
        ],
        dashboardProperties: [{ type: PropertyFilterType.Event, key: '$os', operator: PropertyOperator.IsNotSet }],
    },
    {
        title: 'Same key+value, different group_type_index — compatible (distinct group types)',
        insightProperties: [
            {
                type: PropertyFilterType.Group,
                key: 'name',
                group_type_index: 1,
                operator: PropertyOperator.Exact,
                value: ['Acme'],
            } as AnyPropertyFilter,
        ],
        dashboardProperties: [
            {
                type: PropertyFilterType.Group,
                key: 'name',
                group_type_index: 0,
                operator: PropertyOperator.Exact,
                value: ['Acme'],
            } as AnyPropertyFilter,
        ],
    },
    {
        title: 'icontains needle containing the excluded not_icontains needle — contradicts',
        insightProperties: [
            {
                type: PropertyFilterType.Event,
                key: '$current_url',
                operator: PropertyOperator.IContains,
                value: ['my-example.com/page'],
            },
        ],
        dashboardProperties: [
            {
                type: PropertyFilterType.Event,
                key: '$current_url',
                operator: PropertyOperator.NotIContains,
                value: ['example.com'],
            },
        ],
    },
    {
        title: 'Mixed: one filter contradicts (dropped), one is unrelated (kept)',
        insightProperties: [
            { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: ['Firefox'] },
            {
                type: PropertyFilterType.Event,
                key: '$device_type',
                operator: PropertyOperator.Exact,
                value: ['Desktop'],
            },
        ],
        dashboardProperties: [
            { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: ['Chrome'] },
        ],
    },
]

// One snapshot for all cases so a `filters_contradict` regression shows as one diff, not nine.
export const PropertyFilterConflictCases: Story = {
    render: () => (
        <div className="flex flex-col gap-4">
            {PROPERTY_FILTER_CONFLICT_CASES.map(({ title, insightProperties, dashboardProperties }) => (
                <div key={title} className="bg-surface-primary w-[24rem] p-4 rounded">
                    <div className="text-xs font-semibold text-muted-alt mb-2">{title}</div>
                    <InsightDetailsComponent
                        query={withOwnProperties(insightProperties).query}
                        footerInfo={withOwnProperties(insightProperties)}
                        filtersOverride={{ properties: dashboardProperties }}
                    />
                </div>
            ))}
        </div>
    ),
}
