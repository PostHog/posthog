import type { Meta, StoryObj } from '@storybook/react'

import { ClusteringSkipReasonMessage } from './ClusteringSkipReasonMessage'

const meta: Meta<typeof ClusteringSkipReasonMessage> = {
    title: 'Scenes-App/AI observability/ClusteringSkipReasonMessage',
    component: ClusteringSkipReasonMessage,
    parameters: {
        layout: 'padded',
        testOptions: { snapshotBrowsers: [] },
    },
    args: {
        clusteringLevel: 'trace',
        onManageJobs: () => {},
    },
}
export default meta

type Story = StoryObj<typeof ClusteringSkipReasonMessage>

const noDetails = { item_count: null, min_required: null, checked_at: null }

export const NotEnoughItems: Story = {
    args: {
        skipReason: {
            reason: 'not_enough_items',
            item_count: 240,
            min_required: 1000,
            checked_at: '2026-10-29T04:00:00Z',
        },
    },
}

export const AIDataProcessingNotApproved: Story = {
    args: { skipReason: { reason: 'ai_data_processing_not_approved', ...noDetails } },
}

export const NoEnabledJob: Story = {
    args: { clusteringLevel: 'generation', skipReason: { reason: 'no_enabled_job', ...noDetails } },
}

export const NotScheduled: Story = {
    args: { skipReason: { reason: 'not_scheduled', ...noDetails } },
}
