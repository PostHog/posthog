import { Meta, StoryObj } from '@storybook/react'

import { UsageLimitPaywall } from './UsageLimitPaywall'

const meta: Meta<typeof UsageLimitPaywall> = {
    title: 'Components/Usage Limit Paywall',
    component: UsageLimitPaywall,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    render: (args) => (
        <div className="p-10 max-w-4xl mx-auto">
            <UsageLimitPaywall {...args} />
        </div>
    ),
}
export default meta

type Story = StoryObj<typeof UsageLimitPaywall>

export const Default: Story = {
    args: {
        title: 'AI summary limit reached',
        description: 'Disable an existing AI summary or upgrade your plan to add more.',
        limit: 10,
        currentUsage: 10,
        unit: 'active AI summaries on your plan',
    },
}

export const WithoutCurrentUsage: Story = {
    args: {
        title: 'Cohort limit reached',
        description: 'You have reached the maximum number of cohorts on your current plan.',
        limit: 50,
        unit: 'cohorts',
    },
}

export const WithoutBackground: Story = {
    args: {
        title: 'AI summary limit reached',
        description: 'Disable an existing AI summary or upgrade your plan to add more.',
        limit: 10,
        currentUsage: 12,
        unit: 'active AI summaries on your plan',
        background: false,
    },
}

export const CustomCta: Story = {
    args: {
        title: 'Recordings retention limit',
        description: 'You can store more by upgrading your plan or trimming what you have.',
        limit: 30,
        currentUsage: 30,
        unit: 'days of retention',
        ctaLabel: 'Manage retention',
        ctaTo: '/settings/environment-replay',
    },
}
