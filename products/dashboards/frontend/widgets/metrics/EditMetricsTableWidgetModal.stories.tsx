import type { Meta, StoryObj } from '@storybook/react'

import { widgetStorybookParameters } from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import { EditMetricsTableWidgetModal } from './EditMetricsTableWidgetModal'

const CATALOG = getDashboardWidgetCatalogEntry('metrics_table')
const meta: Meta<typeof EditMetricsTableWidgetModal> = {
    title: 'Products/Dashboards/Dashboard Widgets/Widget types/Metrics/Metrics table/Widget settings',
    component: EditMetricsTableWidgetModal,
    parameters: { layout: 'fullscreen', ...widgetStorybookParameters },
    args: {
        isOpen: true,
        onClose: () => undefined,
        onSave: () => Promise.resolve(),
        config: CATALOG.defaultConfig,
        name: 'Metrics table',
        defaultTitle: 'Metrics table',
        description: CATALOG.description,
    },
}
export default meta
type Story = StoryObj<typeof EditMetricsTableWidgetModal>

export const Default: Story = {}

export const HttpEndpoints: Story = {
    args: {
        config: {
            ...CATALOG.defaultConfig,
            groupBy: 'http.route',
            columns: [
                { label: 'Requests/s', metricName: 'http_server_requests_total', aggregation: 'rate' },
                {
                    label: 'Errors/s',
                    metricName: 'http_server_requests_total',
                    aggregation: 'rate',
                    filters: [{ key: 'http.response.status_code', op: 'regex', value: '5..' }],
                },
                {
                    label: 'p95 latency',
                    metricName: 'http_server_request_duration_seconds',
                    aggregation: 'histogram_quantile',
                    quantile: 0.95,
                },
            ],
        },
    },
}
