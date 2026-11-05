import type { Meta, StoryObj } from '@storybook/react'

import { IconPerson } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { LabeledChipValue } from './LabeledChipValue'

const meta: Meta<typeof LabeledChipValue> = {
    title: 'Scenes-App/AI observability/Trace view/Labeled chip value',
    component: LabeledChipValue,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { label: 'Queue', children: 'Support QA' },
    render: (args) => (
        <LemonTag weight="normal">
            <LabeledChipValue {...args} />
        </LemonTag>
    ),
}
export default meta

type Story = StoryObj<typeof LabeledChipValue>

export const Short: Story = {}
export const LongValueTruncates: Story = {
    args: { label: 'Cluster', children: 'Refund and billing escalations from the enterprise tier' },
}
export const WithIcon: Story = { args: { label: 'Person', icon: <IconPerson />, children: 'ana@example.com' } }
