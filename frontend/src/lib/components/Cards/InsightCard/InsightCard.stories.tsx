import { Meta, Story } from '@storybook/react'
import { useState } from 'react'

import { TileFilters } from '~/queries/schema/schema-general'
import { AccessControlLevel, DashboardTile, InsightColor, InsightShortId, QueryBasedInsightModel } from '~/types'

import EXAMPLE_DATA_TABLE_NODE_EVENTS_QUERY from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableEvents.json'
import EXAMPLE_DATA_TABLE_NODE_HOGQL_QUERY from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json'
import EXAMPLE_FUNNEL from '../../../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'
import EXAMPLE_LIFECYCLE from '../../../../mocks/fixtures/api/projects/team_id/insights/lifecycle.json'
import EXAMPLE_RETENTION from '../../../../mocks/fixtures/api/projects/team_id/insights/retention.json'
import EXAMPLE_STICKINESS from '../../../../mocks/fixtures/api/projects/team_id/insights/stickiness.json'
import EXAMPLE_TRENDS from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import EXAMPLE_TRENDS_BREAKDOWN_MANY from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdownMany.json'
import EXAMPLE_TRENDS_MULTI from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'
import EXAMPLE_TRENDS_PIE from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'
import EXAMPLE_TRENDS_TABLE from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json'
import EXAMPLE_TRENDS_HORIZONTAL_BAR from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'
import EXAMPLE_TRENDS_WORLD_MAP from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'
import { InsightCard as InsightCardComponent } from './index'

const defaultTile = {
    id: 1,
    filters_overrides: {
        properties: [
            {
                key: '$browser',
                operator: 'exact',
                type: 'event',
                value: ['Chrome'],
            },
        ],
    } as TileFilters,
} as DashboardTile<QueryBasedInsightModel>

const examples = [
    EXAMPLE_TRENDS,
    EXAMPLE_TRENDS_MULTI,
    EXAMPLE_TRENDS_BREAKDOWN_MANY,
    EXAMPLE_TRENDS_HORIZONTAL_BAR,
    EXAMPLE_TRENDS_TABLE,
    EXAMPLE_TRENDS_PIE,
    EXAMPLE_TRENDS_WORLD_MAP,
    EXAMPLE_FUNNEL,
    EXAMPLE_RETENTION,
    EXAMPLE_STICKINESS,
    EXAMPLE_LIFECYCLE,
    EXAMPLE_DATA_TABLE_NODE_HOGQL_QUERY,
    EXAMPLE_DATA_TABLE_NODE_EVENTS_QUERY,
] as unknown as QueryBasedInsightModel[]

const meta: Meta = {
    title: 'Components/Cards/Insight Card',
    component: InsightCardComponent,
    parameters: {
        mockDate: '2023-07-01',
    },
    argTypes: {
        insightName: {
            control: { type: 'text' },
        },
        insightDescription: {
            control: { type: 'text' },
        },
        loading: {
            control: { type: 'boolean' },
        },
        apiErrored: {
            control: { type: 'boolean' },
        },
        timedOut: {
            control: { type: 'boolean' },
        },
        highlighted: {
            control: { type: 'boolean' },
        },
        tile: defaultTile,
    },
}
export default meta
export const InsightCard: Story = (args) => {
    const [insightColor, setInsightColor] = useState<InsightColor | null>(null)
    const [wasItemRemoved, setWasItemRemoved] = useState(false)

    return (
        <div className="grid gap-4 grid-cols-2 min-w-[50rem]">
            {!wasItemRemoved && (
                <InsightCardComponent
                    tile={args.tile}
                    insight={
                        {
                            ...EXAMPLE_TRENDS,
                            name: args.insightName,
                            description: args.insightDescription,
                        } as unknown as QueryBasedInsightModel
                    }
                    ribbonColor={insightColor}
                    loading={args.loading}
                    apiErrored={args.apiErrored}
                    highlighted={args.highlighted}
                    timedOut={args.timedOut}
                    showResizeHandles={args.resizable}
                    updateColor={setInsightColor}
                    removeFromDashboard={() => setWasItemRemoved(true)}
                    rename={() => {}}
                    duplicate={() => {}}
                    placement="SavedInsightGrid"
                />
            )}
            <InsightCardComponent
                tile={args.tile}
                insight={
                    {
                        ...EXAMPLE_TRENDS,
                        name: 'Wow, this name is really super duper ginormously off the charts long! How do we even manage to fit it in an insight card without it breaking?!',
                        description:
                            'Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo. Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit, sed quia consequuntur magni dolores eos qui ratione voluptatem sequi nesciunt.',
                        tags: ['every', 'green', 'bus', 'drives', 'fast', 'face'],
                    } as unknown as QueryBasedInsightModel
                }
                rename={() => {}}
                duplicate={() => {}}
                placement="SavedInsightGrid"
                loading={args.loading}
                apiErrored={args.apiErrored}
                highlighted={args.highlighted}
                timedOut={args.timedOut}
                showResizeHandles={args.resizable}
            />
            <InsightCardComponent
                tile={args.tile}
                insight={
                    {
                        ...EXAMPLE_TRENDS,
                        name: '',
                        description: '',
                        last_modified_by: null,
                    } as unknown as QueryBasedInsightModel
                }
                rename={() => {}}
                duplicate={() => {}}
                placement="SavedInsightGrid"
                loading={args.loading}
                apiErrored={args.apiErrored}
                highlighted={args.highlighted}
                timedOut={args.timedOut}
                showResizeHandles={args.resizable}
            />
            <InsightCardComponent
                tile={args.tile}
                insight={
                    {
                        ...EXAMPLE_FUNNEL,
                        short_id: 'funnel_empty' as InsightShortId,
                        query: {
                            ...EXAMPLE_FUNNEL.query,
                            source: {
                                ...EXAMPLE_FUNNEL.query.source,
                                series: EXAMPLE_FUNNEL.query.source.series.slice(0, 1),
                            },
                        },
                        name: 'What a pitiful funnel',
                    } as unknown as QueryBasedInsightModel
                }
                rename={() => {}}
                duplicate={() => {}}
                placement="SavedInsightGrid"
                loading={args.loading}
                apiErrored={args.apiErrored}
                highlighted={args.highlighted}
                timedOut={args.timedOut}
                showResizeHandles={args.resizable}
            />
            <InsightCardComponent
                tile={args.tile}
                insight={
                    {
                        ...EXAMPLE_FUNNEL,
                        name: 'What a plentiful funnel',
                    } as unknown as QueryBasedInsightModel
                }
                rename={() => {}}
                duplicate={() => {}}
                placement="SavedInsightGrid"
                loading={args.loading}
                apiErrored={args.apiErrored}
                highlighted={args.highlighted}
                timedOut={args.timedOut}
                showResizeHandles={args.resizable}
            />
            {examples.map((e) => (
                <InsightCardComponent
                    tile={args.tile}
                    key={e.id}
                    insight={e as unknown as QueryBasedInsightModel}
                    rename={() => {}}
                    duplicate={() => {}}
                    placement="SavedInsightGrid"
                    loading={args.loading}
                    apiErrored={args.apiErrored}
                    highlighted={args.highlighted}
                    timedOut={args.timedOut}
                    showResizeHandles={args.resizable}
                />
            ))}
        </div>
    )
}

// Access Control Stories
export const AccessControlNoAccess: Story = () => {
    return (
        <div className="grid gap-4 grid-cols-2 min-w-[50rem]">
            <InsightCardComponent
                tile={defaultTile}
                insight={
                    {
                        ...EXAMPLE_TRENDS,
                        name: 'Sales Analysis - Restricted',
                        description: 'This insight contains sensitive sales data.',
                        user_access_level: 'none',
                    } as unknown as QueryBasedInsightModel
                }
                rename={() => {}}
                duplicate={() => {}}
                placement="SavedInsightGrid"
            />
        </div>
    )
}

export const AccessControlViewerAccess: Story = () => {
    const [insightColor, setInsightColor] = useState<InsightColor | null>(null)

    return (
        <div className="grid gap-4 grid-cols-2 min-w-[50rem]">
            <InsightCardComponent
                tile={defaultTile}
                insight={
                    {
                        ...EXAMPLE_TRENDS,
                        name: 'User Engagement Metrics - View Only',
                        description: 'You can view this insight but cannot edit it.',
                        user_access_level: AccessControlLevel.Viewer,
                    } as unknown as QueryBasedInsightModel
                }
                ribbonColor={insightColor}
                updateColor={setInsightColor}
                rename={() => {}}
                duplicate={() => {}}
                placement="SavedInsightGrid"
            />
        </div>
    )
}

export const AccessControlEditorAccess: Story = () => {
    const [insightColor, setInsightColor] = useState<InsightColor | null>(null)
    const [wasItemRemoved, setWasItemRemoved] = useState(false)

    return (
        <div className="grid gap-4 grid-cols-2 min-w-[50rem]">
            {!wasItemRemoved && (
                <InsightCardComponent
                    tile={defaultTile}
                    insight={
                        {
                            ...EXAMPLE_TRENDS,
                            name: 'Product Analytics - Full Access',
                            description: 'You can view, edit, and manage this insight.',
                            user_access_level: AccessControlLevel.Editor,
                        } as unknown as QueryBasedInsightModel
                    }
                    ribbonColor={insightColor}
                    updateColor={setInsightColor}
                    removeFromDashboard={() => setWasItemRemoved(true)}
                    rename={() => {}}
                    duplicate={() => {}}
                    placement="SavedInsightGrid"
                />
            )}
        </div>
    )
}

export const AccessControlManagerAccess: Story = () => {
    const [insightColor, setInsightColor] = useState<InsightColor | null>(null)
    const [wasItemRemoved, setWasItemRemoved] = useState(false)

    return (
        <div className="grid gap-4 grid-cols-2 min-w-[50rem]">
            {!wasItemRemoved && (
                <InsightCardComponent
                    tile={defaultTile}
                    insight={
                        {
                            ...EXAMPLE_TRENDS,
                            name: 'Executive Dashboard - Manager Access',
                            description: 'You have full management permissions for this insight.',
                            user_access_level: AccessControlLevel.Manager,
                        } as unknown as QueryBasedInsightModel
                    }
                    ribbonColor={insightColor}
                    updateColor={setInsightColor}
                    removeFromDashboard={() => setWasItemRemoved(true)}
                    deleteWithUndo={async () => {}}
                    rename={() => {}}
                    duplicate={() => {}}
                    placement="SavedInsightGrid"
                />
            )}
        </div>
    )
}

export const AccessControlLegacyInsight: Story = () => {
    const [insightColor, setInsightColor] = useState<InsightColor | null>(null)
    const [wasItemRemoved, setWasItemRemoved] = useState(false)

    return (
        <div className="grid gap-4 grid-cols-2 min-w-[50rem]">
            {!wasItemRemoved && (
                <InsightCardComponent
                    tile={defaultTile}
                    insight={
                        {
                            ...EXAMPLE_TRENDS,
                            name: 'Legacy Insight - No Access Control',
                            description: 'This insight was created before access control was implemented.',
                            // user_access_level is intentionally undefined to test fallback behavior
                        } as unknown as QueryBasedInsightModel
                    }
                    ribbonColor={insightColor}
                    updateColor={setInsightColor}
                    removeFromDashboard={() => setWasItemRemoved(true)}
                    deleteWithUndo={async () => {}}
                    rename={() => {}}
                    duplicate={() => {}}
                    placement="SavedInsightGrid"
                />
            )}
        </div>
    )
}

export const AccessControlMixedPermissions: Story = () => {
    const [insightColor, setInsightColor] = useState<InsightColor | null>(null)

    return (
        <div className="grid gap-4 grid-cols-3 min-w-[75rem]">
            {/* No Access */}
            <InsightCardComponent
                tile={defaultTile}
                insight={
                    {
                        ...EXAMPLE_TRENDS,
                        name: 'Restricted Data',
                        user_access_level: 'none',
                    } as unknown as QueryBasedInsightModel
                }
                rename={() => {}}
                duplicate={() => {}}
                placement="SavedInsightGrid"
            />

            {/* Viewer Access */}
            <InsightCardComponent
                tile={defaultTile}
                insight={
                    {
                        ...EXAMPLE_FUNNEL,
                        name: 'View Only Funnel',
                        user_access_level: AccessControlLevel.Viewer,
                    } as unknown as QueryBasedInsightModel
                }
                ribbonColor={insightColor}
                updateColor={setInsightColor}
                rename={() => {}}
                duplicate={() => {}}
                placement="SavedInsightGrid"
            />

            {/* Editor Access */}
            <InsightCardComponent
                tile={defaultTile}
                insight={
                    {
                        ...EXAMPLE_RETENTION,
                        name: 'Editable Retention',
                        user_access_level: AccessControlLevel.Editor,
                    } as unknown as QueryBasedInsightModel
                }
                ribbonColor={insightColor}
                updateColor={setInsightColor}
                removeFromDashboard={() => {}}
                deleteWithUndo={async () => {}}
                rename={() => {}}
                duplicate={() => {}}
                placement="SavedInsightGrid"
            />
        </div>
    )
}
