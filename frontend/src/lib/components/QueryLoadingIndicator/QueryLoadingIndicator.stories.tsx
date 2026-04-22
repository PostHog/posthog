import { Meta, StoryFn } from '@storybook/react'

import { QueryLoadingIndicator, QueryLoadingIndicatorProps } from './QueryLoadingIndicator'

const meta: Meta<typeof QueryLoadingIndicator> = {
    title: 'Components/Query Loading Indicator',
    component: QueryLoadingIndicator,
    parameters: {
        layout: 'centered',
        docs: {
            description: {
                component:
                    'A reusable loading indicator for queries that shows full state on initial load and subtle loading bar when refreshing cached results.',
            },
        },
    },
    tags: ['autodocs'],
}

export default meta

const Template: StoryFn<QueryLoadingIndicatorProps> = (args) => (
    <div style={{ width: '600px' }}>
        <QueryLoadingIndicator {...args} />
    </div>
)

export const InitialLoad = Template.bind({})
InitialLoad.args = {
    queryId: 'test-query-123',
    hasCachedResults: false,
    showDetails: true,
    height: 300,
}

export const InitialLoadWithoutDetails = Template.bind({})
InitialLoadWithoutDetails.args = {
    queryId: 'test-query-456',
    hasCachedResults: false,
    showDetails: false,
    height: 200,
}

export const CachedResultsRefresh = Template.bind({})
CachedResultsRefresh.args = {
    queryId: 'test-query-789',
    hasCachedResults: true,
    showDetails: true,
    height: 80,
}

export const WithProgressDetails = Template.bind({})
WithProgressDetails.args = {
    queryId: 'test-query-progress',
    hasCachedResults: false,
    showDetails: true,
    height: 300,
    pollResponse: {
        status: {
            query_progress: {
                rows_read: 1500000,
                bytes_read: 52428800, // 50 MB
                estimated_rows_total: 2000000,
                active_cpu_time: 8500,
                time_elapsed: 10000,
            },
            start_time: new Date(Date.now() - 5000).toISOString(),
        },
        previousStatus: {
            query_progress: {
                rows_read: 1000000,
                bytes_read: 34952806, // ~33 MB
                estimated_rows_total: 2000000,
                active_cpu_time: 7000,
                time_elapsed: 8000,
            },
        },
    },
}

export const CustomSuggestion = Template.bind({})
CustomSuggestion.args = {
    queryId: 'test-query-custom',
    hasCachedResults: false,
    showDetails: false,
    height: 250,
    suggestion: (
        <div className="text-xs text-center">
            <p className="m-0">This is taking longer than expected.</p>
            <p className="m-0">Try filtering by a specific property.</p>
        </div>
    ),
}

export const InChartCell = Template.bind({})
InChartCell.args = {
    queryId: 'test-query-chart',
    hasCachedResults: false,
    showDetails: false,
    height: 40,
}

export const CachedInChartCell = Template.bind({})
CachedInChartCell.args = {
    queryId: 'test-query-chart-cached',
    hasCachedResults: true,
    showDetails: false,
    height: 40,
}
