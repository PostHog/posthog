import type { Meta, StoryObj } from '@storybook/react'

import type { EvaluationReportRun } from '../types'
import { ReportDeliveryTag } from './ReportDeliveryTag'

const meta: Meta<typeof ReportDeliveryTag> = {
    title: 'Scenes-App/AI observability/Evaluation reports/Delivery tag',
    component: ReportDeliveryTag,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta
type Story = StoryObj<typeof ReportDeliveryTag>

const STATES: [string, Pick<EvaluationReportRun, 'delivery_status' | 'delivery_destinations'>][] = [
    [
        'Delivered to Slack and email',
        {
            delivery_status: 'delivered',
            delivery_destinations: [
                { type: 'slack', name: 'evals' },
                { type: 'email', name: 'team@example.com' },
            ],
        },
    ],
    ['Delivered before destinations were recorded', { delivery_status: 'delivered', delivery_destinations: [] }],
    ['Not sent anywhere', { delivery_status: 'generated', delivery_destinations: [] }],
    ['Sending', { delivery_status: 'pending', delivery_destinations: [] }],
    ['Partial failure', { delivery_status: 'partial_failure', delivery_destinations: [] }],
    ['Failed', { delivery_status: 'failed', delivery_destinations: [] }],
]

export const AllStates: Story = {
    render: () => (
        <ul className="flex flex-col gap-3 p-4">
            {STATES.map(([label, run]) => (
                <li key={label} className="flex items-center gap-4">
                    <span className="w-80 text-sm text-secondary">{label}</span>
                    <ReportDeliveryTag run={run} />
                </li>
            ))}
        </ul>
    ),
}
