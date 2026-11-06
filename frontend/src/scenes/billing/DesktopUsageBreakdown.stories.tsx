import { Meta, StoryObj } from '@storybook/react'

import { BillingType } from '~/types'

import { DesktopUsageBreakdown } from './DesktopUsageBreakdown'

type UsageSummary = BillingType['usage_summary']

const summary = ({
    tokenCredits,
    computeCredits,
    cpuMillicoreSeconds,
    memoryMibSeconds,
}: {
    tokenCredits: number
    computeCredits: number
    cpuMillicoreSeconds?: number
    memoryMibSeconds?: number
}): UsageSummary => ({
    posthog_code_token_credits: { usage: tokenCredits },
    sandbox_compute_credits: { usage: computeCredits },
    sandbox_compute_cpu_millicore_seconds: { usage: cpuMillicoreSeconds },
    sandbox_compute_memory_mib_seconds: { usage: memoryMibSeconds },
})

const meta: Meta<typeof DesktopUsageBreakdown> = {
    title: 'Scenes-Other/Billing/DesktopUsageBreakdown',
    component: DesktopUsageBreakdown,
    parameters: { layout: 'padded' },
    decorators: [
        (Story) => (
            <div className="w-[720px] max-w-full">
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof DesktopUsageBreakdown>

export const UsageMix: Story = {
    args: {
        summary: summary({
            tokenCredits: 1_250,
            computeCredits: 750,
            cpuMillicoreSeconds: 45_000,
            memoryMibSeconds: 92_160,
        }),
    },
}

export const NoUsage: Story = {
    args: {
        summary: summary({
            tokenCredits: 0,
            computeCredits: 0,
            cpuMillicoreSeconds: 0,
            memoryMibSeconds: 0,
        }),
    },
}

export const ResourcesUnavailable: Story = {
    args: {
        summary: summary({
            tokenCredits: 1_250,
            computeCredits: 750,
        }),
    },
}
