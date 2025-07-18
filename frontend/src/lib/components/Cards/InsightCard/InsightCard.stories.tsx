import { Meta, Story } from '@storybook/react'
import { useState } from 'react'

import { InsightColor, InsightShortId, QueryBasedInsightModel } from '~/types'

import EXAMPLE_DATA_TABLE_NODE_EVENTS_QUERY_DATA from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableEvents.json'
import EXAMPLE_DATA_TABLE_NODE_HOGQL_QUERY_DATA from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json'
import EXAMPLE_FUNNEL_DATA from '../../../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'
import EXAMPLE_LIFECYCLE_DATA from '../../../../mocks/fixtures/api/projects/team_id/insights/lifecycle.json'
import EXAMPLE_RETENTION_DATA from '../../../../mocks/fixtures/api/projects/team_id/insights/retention.json'
import EXAMPLE_STICKINESS_DATA from '../../../../mocks/fixtures/api/projects/team_id/insights/stickiness.json'
import EXAMPLE_TRENDS_DATA from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import EXAMPLE_TRENDS_BREAKDOWN_MANY_DATA from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdownMany.json'
import EXAMPLE_TRENDS_MULTI_DATA from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'
import EXAMPLE_TRENDS_PIE_DATA from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'
import EXAMPLE_TRENDS_TABLE_DATA from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json'
import EXAMPLE_TRENDS_HORIZONTAL_BAR_DATA from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'
import EXAMPLE_TRENDS_WORLD_MAP_DATA from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'
import { InsightCard as InsightCardComponent } from './index'

const EXAMPLE_DATA_TABLE_NODE_EVENTS_QUERY = EXAMPLE_DATA_TABLE_NODE_EVENTS_QUERY_DATA as unknown as any
const EXAMPLE_DATA_TABLE_NODE_HOGQL_QUERY = EXAMPLE_DATA_TABLE_NODE_HOGQL_QUERY_DATA as unknown as any
const EXAMPLE_FUNNEL = EXAMPLE_FUNNEL_DATA as unknown as any
const EXAMPLE_LIFECYCLE = EXAMPLE_LIFECYCLE_DATA as unknown as any
const EXAMPLE_RETENTION = EXAMPLE_RETENTION_DATA as unknown as any
const EXAMPLE_STICKINESS = EXAMPLE_STICKINESS_DATA as unknown as any
const EXAMPLE_TRENDS = EXAMPLE_TRENDS_DATA as unknown as any
const EXAMPLE_TRENDS_MULTI = EXAMPLE_TRENDS_MULTI_DATA as unknown as any
const EXAMPLE_TRENDS_BREAKDOWN_MANY = EXAMPLE_TRENDS_BREAKDOWN_MANY_DATA as unknown as any
const EXAMPLE_TRENDS_HORIZONTAL_BAR = EXAMPLE_TRENDS_HORIZONTAL_BAR_DATA as unknown as any
const EXAMPLE_TRENDS_TABLE = EXAMPLE_TRENDS_TABLE_DATA as unknown as any
const EXAMPLE_TRENDS_PIE = EXAMPLE_TRENDS_PIE_DATA as unknown as any
const EXAMPLE_TRENDS_WORLD_MAP = EXAMPLE_TRENDS_WORLD_MAP_DATA as unknown as any

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
