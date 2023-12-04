import { Meta, Story } from '@storybook/react'
import { useState } from 'react'

import { ChartDisplayType, InsightColor, InsightModel, InsightShortId, TrendsFilterType } from '~/types'

import EXAMPLE_DATA_TABLE_NODE_EVENTS_QUERY from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableEvents.json'
import EXAMPLE_DATA_TABLE_NODE_HOGQL_QUERY from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json'
import EXAMPLE_FUNNEL from '../../../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'
import EXAMPLE_LIFECYCLE from '../../../../mocks/fixtures/api/projects/team_id/insights/lifecycle.json'
import EXAMPLE_RETENTION from '../../../../mocks/fixtures/api/projects/team_id/insights/retention.json'
import EXAMPLE_STICKINESS from '../../../../mocks/fixtures/api/projects/team_id/insights/stickiness.json'
import EXAMPLE_TRENDS from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import EXAMPLE_TRENDS_MULTI from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'
import EXAMPLE_TRENDS_PIE from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'
import EXAMPLE_TRENDS_TABLE from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json'
import EXAMPLE_TRENDS_HORIZONTAL_BAR from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'
import EXAMPLE_TRENDS_WORLD_MAP from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'
import EXAMPLE_PATHS from '../../../../mocks/fixtures/api/projects/team_id/insights/userPaths.json'
import { InsightCard as InsightCardComponent } from './index'

const examples = [
    EXAMPLE_TRENDS,
    EXAMPLE_TRENDS_MULTI,
    EXAMPLE_TRENDS_HORIZONTAL_BAR,
    EXAMPLE_TRENDS_TABLE,
    EXAMPLE_TRENDS_PIE,
    EXAMPLE_TRENDS_WORLD_MAP,
    EXAMPLE_FUNNEL,
    EXAMPLE_RETENTION,
    EXAMPLE_PATHS,
    EXAMPLE_STICKINESS,
    EXAMPLE_LIFECYCLE,
    EXAMPLE_DATA_TABLE_NODE_HOGQL_QUERY,
    EXAMPLE_DATA_TABLE_NODE_EVENTS_QUERY,
] as unknown as InsightModel[]

const meta: Meta = {
    title: 'Components/Cards/Insight Card',
    component: InsightCardComponent,
    parameters: {
        mockDate: '2023-07-01',
        featureFlags: ['hogql'],
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
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'repeat(2, 1fr)', minWidth: '50rem' }}>
            {!wasItemRemoved && (
                <InsightCardComponent
                    insight={
                        {
                            ...EXAMPLE_TRENDS,
                            name: args.insightName,
                            description: args.insightDescription,
                        } as unknown as InsightModel
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
                    placement={'SavedInsightGrid'}
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
                    } as unknown as InsightModel
                }
                rename={() => {}}
                duplicate={() => {}}
                placement={'SavedInsightGrid'}
            />
            <InsightCardComponent
                insight={
                    { ...EXAMPLE_TRENDS, name: '', description: '', last_modified_by: null } as unknown as InsightModel
                }
                rename={() => {}}
                duplicate={() => {}}
                placement={'SavedInsightGrid'}
            />
            <InsightCardComponent
                insight={
                    {
                        ...EXAMPLE_FUNNEL,
                        short_id: 'funnel_empty' as InsightShortId,
                        filters: { ...EXAMPLE_FUNNEL.filters, events: EXAMPLE_FUNNEL.filters.events?.slice(0, 1) },
                        name: 'What a pitiful funnel',
                    } as unknown as InsightModel
                }
                rename={() => {}}
                duplicate={() => {}}
                placement={'SavedInsightGrid'}
            />
            <InsightCardComponent
                insight={{ ...EXAMPLE_FUNNEL, name: 'What a plentiful funnel' } as unknown as InsightModel}
                rename={() => {}}
                duplicate={() => {}}
                placement={'SavedInsightGrid'}
            />
            <InsightCardComponent
                insight={
                    {
                        ...EXAMPLE_TRENDS,
                        filters: {
                            ...EXAMPLE_TRENDS.filters,
                            display: 'totally_wrong_display_type' as ChartDisplayType,
                        } as TrendsFilterType,
                    } as unknown as InsightModel
                }
                rename={() => {}}
                duplicate={() => {}}
                placement={'SavedInsightGrid'}
            />
            {examples.map((e) => (
                <InsightCardComponent
                    key={e.id}
                    insight={e}
                    rename={() => {}}
                    duplicate={() => {}}
                    placement={'SavedInsightGrid'}
                />
            ))}
        </div>
    )
}
