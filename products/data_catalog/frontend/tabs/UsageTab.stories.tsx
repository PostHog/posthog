import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { PARTLY_FAILED_USAGE_SNAPSHOT, USAGE_SNAPSHOT, USAGE_STORY_METRICS } from '../usageStoryFixtures'
import { UsageTab } from './UsageTab'

interface StoryProps {
    hasScan: boolean
    partlyFailed?: boolean
}

const meta: Meta<StoryProps> = {
    title: 'Data catalog/Usage tab',
    args: { hasScan: true },
    parameters: { mockDate: '2026-10-30', viewMode: 'story' },
    render: ({ hasScan, partlyFailed }) => {
        const snapshot = partlyFailed ? PARTLY_FAILED_USAGE_SNAPSHOT : USAGE_SNAPSHOT
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/data_catalog/metrics/': USAGE_STORY_METRICS,
                '/api/projects/:team_id/data_catalog/usage/': hasScan ? [snapshot] : [],
                '/api/projects/:team_id/data_catalog/usage/latest/': hasScan
                    ? snapshot
                    : () => [404, { detail: 'No usage scan has finished for this project yet.' }],
            },
        })
        return <UsageTab />
    },
}

export default meta
type Story = StoryObj<StoryProps>
export const WithScan: Story = {}
export const NoScanYet: Story = { args: { hasScan: false } }
export const PartlyFailed: Story = { args: { partlyFailed: true } }
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-128">
                <Story />
            </div>
        ),
    ],
}
