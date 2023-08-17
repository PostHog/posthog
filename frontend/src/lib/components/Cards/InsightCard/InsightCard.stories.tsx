import { Meta, Story } from '@storybook/react'
import { useState } from 'react'
import { ChartDisplayType, InsightColor, InsightModel, InsightShortId, TrendsFilterType } from '~/types'
import { InsightCard as InsightCardComponent } from './index'

import EXAMPLE_TRENDS from './__mocks__/trends.json'
import EXAMPLE_TRENDS_HORIZONTAL_BAR from './__mocks__/trendsHorizontalBar.json'
import EXAMPLE_TRENDS_TABLE from './__mocks__/trendsTable.json'
import EXAMPLE_TRENDS_PIE from './__mocks__/trendsPie.json'
import EXAMPLE_TRENDS_WORLD_MAP from './__mocks__/trendsWorldMap.json'
import EXAMPLE_FUNNEL from './__mocks__/funnel.json'
import EXAMPLE_RETENTION from './__mocks__/retention.json'
import EXAMPLE_PATHS from './__mocks__/paths.json'
import EXAMPLE_STICKINESS from './__mocks__/stickiness.json'
import EXAMPLE_LIFECYCLE from './__mocks__/lifecycle.json'
import EXAMPLE_DATA_TABLE_NODE_HOGQL_QUERY from './__mocks__/dataTableHogQL.json'
import EXAMPLE_DATA_TABLE_NODE_EVENTS_QUERY from './__mocks__/dataTableEvents.json'

const examples = [
    EXAMPLE_TRENDS,
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
            defaultValue: 'Insight title (edit in story controls)',
        },
        insightDescription: {
            control: { type: 'text' },
            defaultValue: 'Insight description (edit in story controls)',
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
