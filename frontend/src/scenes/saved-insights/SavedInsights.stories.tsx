import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { buildMarkdownNotebookContent } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

import funnelTopToBottom from '../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import trendsBarBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'
import trendsPieBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'
import insightsJson from './__mocks__/insights.json'

const insights = [trendsBarBreakdown, trendsPieBreakdown, funnelTopToBottom]

const homeNotebook = {
    id: 'product-analytics-home',
    short_id: 'pa-home-v1',
    title: 'Product analytics home',
    content: buildMarkdownNotebookContent(`# Product analytics home

This notebook is shared with everyone in this project. Edit the insights and notes to match your product.

<Query nodeId="daily-active-users" query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","dateRange":{"date_from":"-30d","date_to":null},"interval":"day","series":[{"kind":"EventsNode","event":null,"name":"All events","math":"dau","custom_name":"Daily active users"}],"trendsFilter":{"display":"ActionsLineGraph"}},"showHeader":true}} title="Daily active users" />

<Query nodeId="event-volume" query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","dateRange":{"date_from":"-30d","date_to":null},"interval":"day","series":[{"kind":"EventsNode","event":null,"name":"All events","math":"total","custom_name":"Events"}],"trendsFilter":{"display":"ActionsLineGraph"}},"showHeader":true}} title="Event volume" />

<Query nodeId="user-retention" query={{"kind":"InsightVizNode","source":{"kind":"RetentionQuery","retentionFilter":{"period":"Day","totalIntervals":8,"targetEntity":{"name":"All events","type":"events"},"returningEntity":{"name":"All events","type":"events"},"retentionType":"retention_first_time","meanRetentionCalculation":"simple"}},"showHeader":true}} title="User retention" />

<Query nodeId="user-lifecycle" query={{"kind":"InsightVizNode","source":{"kind":"LifecycleQuery","dateRange":{"date_from":"-12w","date_to":null},"interval":"week","series":[{"kind":"EventsNode","event":null,"name":"All events"}]},"showHeader":true}} title="User lifecycle" />

<Query nodeId="top-events" query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","dateRange":{"date_from":"-7d","date_to":null},"interval":"day","series":[{"kind":"EventsNode","event":null,"name":"All events","math":"total","custom_name":"Events"}],"breakdownFilter":{"breakdown":"event","breakdown_type":"event_metadata","breakdown_limit":10},"trendsFilter":{"display":"ActionsTable"}},"showHeader":true}} title="Top events in the last 7 days" />`),
    text_content: 'Product analytics home',
    version: 0,
    deleted: false,
    created_at: '2023-02-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2023-02-01T00:00:00Z',
    last_modified_by: null,
    user_access_level: 'editor',
    parent_resource: null,
    variables: null,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Saved Insights',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-18',
        pageUrl: urls.insights(),
        testOptions: { viewport: { width: 1300, height: 2000 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights': toPaginatedResponse(
                    insightsJson.results.slice(0, 6).map((result, i) => ({
                        // Keep size of response in check
                        ...result,
                        query: insights[i % insights.length].query,
                        result: insights[i % insights.length].result,
                    }))
                ),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const ListView: Story = {}

export const Home: Story = {
    parameters: {
        featureFlags: { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB]: 'test' },
        pageUrl: `${urls.savedInsights()}?tab=home`,
        testOptions: { viewport: { width: 1300, height: 2000 }, waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/notebooks/pa-home-v1/': homeNotebook,
                '/api/projects/:team_id/notebooks/kernel/compute_options/': {
                    currency: 'USD',
                    cpu_rate_per_core_hour: 0.2,
                    memory_rate_per_gb_hour: 0.025,
                    default_preset_key: 'small',
                    presets: [
                        {
                            key: 'small',
                            name: 'Small',
                            description: 'Small notebook compute',
                            cpu_cores: 1,
                            memory_gb: 2,
                            hourly_price: 0.25,
                        },
                    ],
                    allowed_cpu_cores: [1],
                    allowed_memory_gb: [2],
                    allowed_idle_timeout_seconds: [3600],
                },
                '/api/projects/:team_id/insights/': toPaginatedResponse(insightsJson.results.slice(0, 1)),
            },
            post: {
                '/api/environments/:team_id/query/': { results: [] },
                '/api/environments/:team_id/persons/batch_by_distinct_ids/': { results: {} },
            },
        }),
    ],
}

export const HomeWithBooleanFlag: Story = {
    ...Home,
    parameters: {
        ...Home.parameters,
        featureFlags: { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB]: true },
    },
}

export const EmptyState: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
}

export const ErrorState: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights': () => [500, { detail: 'Internal server error' }],
            },
        }),
    ],
}

export const SearchResults: Story = {
    parameters: {
        pageUrl: urls.savedInsights() + '?search=revenue',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights': toPaginatedResponse(
                    insightsJson.results.slice(0, 5).map((result, i) => {
                        const exactNames = ['Revenue by region', 'Weekly revenue']
                        const similarNames = ['Reveneu trends', 'Q4 reveue', 'Revanue dashboard']
                        const isExact = i < exactNames.length
                        return {
                            ...result,
                            name: isExact ? exactNames[i] : similarNames[i - exactNames.length],
                            query: insights[i % insights.length].query,
                            result: insights[i % insights.length].result,
                            search_match_type: isExact ? 'exact' : 'similar',
                        }
                    })
                ),
            },
        }),
    ],
}
