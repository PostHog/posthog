import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { widgetStorybookParameters } from '../../components/WidgetCard/widgetCardStoryFixtures'
import type { DashboardWidgetEditModalProps } from '../registry'
import { EditMetricsWidgetModal } from './EditMetricsWidgetModal'
import { metricsWidgetDefaultConfig } from './metricsWidgetConfig'
import { METRICS_WIDGET_SAMPLE_RESPONSE, metricsWidgetSampleQuery } from './metricsWidgetSampleData'

const METRIC_NAMES = {
    results: [
        { name: 'http_server_requests', metric_type: 'sum' },
        { name: 'http_server_request_duration', metric_type: 'histogram' },
        { name: 'process_cpu_utilization', metric_type: 'gauge' },
    ],
}

const metricsApiMock = mswDecorator({
    get: {
        '/api/projects/:team_id/metrics/names/': () => [200, METRIC_NAMES],
        '/api/environments/:team_id/metrics/names/': () => [200, METRIC_NAMES],
    },
    post: {
        '/api/environments/:team_id/query/:kind/': () => [200, METRICS_WIDGET_SAMPLE_RESPONSE],
        '/api/projects/:team_id/query/:kind/': () => [200, METRICS_WIDGET_SAMPLE_RESPONSE],
    },
})

type EditMetricsWidgetModalStoryProps = Partial<DashboardWidgetEditModalProps>

function EditMetricsWidgetModalStory({
    isOpen = true,
    onClose = () => undefined,
    onSave = () => Promise.resolve(),
    config = metricsWidgetDefaultConfig('line'),
    name = '',
    defaultTitle = 'Metric',
    description = '',
    ...props
}: EditMetricsWidgetModalStoryProps): JSX.Element {
    return (
        <EditMetricsWidgetModal
            isOpen={isOpen}
            onClose={onClose}
            config={config}
            onSave={onSave}
            name={name}
            defaultTitle={defaultTitle}
            description={description}
            {...props}
        />
    )
}

// Storybook CSF requires a string literal `title` derived from catalog groupLabel/label.
const meta: Meta<typeof EditMetricsWidgetModalStory> = {
    title: 'Products/Dashboards/Dashboard Widgets/Widget types/Metrics/Metric/Widget settings',
    component: EditMetricsWidgetModalStory,
    parameters: {
        layout: 'fullscreen',
        ...widgetStorybookParameters,
        featureFlags: [
            FEATURE_FLAGS.METRICS,
            FEATURE_FLAGS.METRICS_INSIGHT_BUILDER,
            FEATURE_FLAGS.METRICS_QUERY_LANGUAGES,
        ],
    },
    decorators: [metricsApiMock],
}

export default meta

type Story = StoryObj<typeof EditMetricsWidgetModalStory>

export const NewWidget: Story = {}

export const WithMetric: Story = {
    args: {
        config: { query: metricsWidgetSampleQuery('time_series') },
        name: 'Requests by service',
        description: 'Request rate per service over the last hour.',
    },
}
