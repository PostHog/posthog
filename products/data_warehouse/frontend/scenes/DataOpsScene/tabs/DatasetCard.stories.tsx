import type { Meta, StoryObj } from '@storybook/react'

import { IconGroups } from '@posthog/icons'

import { DatasetCard } from './DatasetCard'

const meta: Meta<typeof DatasetCard> = {
    title: 'Scenes-App/Data Warehouse/Data ops/Dataset card',
    component: DatasetCard,
    parameters: {
        mockDate: '2026-07-13T12:00:00Z',
    },
    args: {
        title: 'Groups',
        description: 'Historical groups and warehouse updates',
        icon: <IconGroups />,
        status: {
            dataset: 'groups',
            readiness_state: 'backfilling',
            detail: 'Historical data is being copied into the warehouse.',
            completed_partitions: 0,
            total_partitions: 1,
            current_partition: '1',
            last_updated_at: '2026-07-13T11:55:00Z',
        },
    },
    decorators: [
        (Story) => (
            <div className="w-80">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof DatasetCard>

export const FullExport: Story = {}

export const Loaded: Story = {
    args: {
        status: {
            dataset: 'groups',
            readiness_state: 'up_to_date',
            detail: 'Historical group data is loaded.',
            completed_partitions: 1,
            total_partitions: 1,
            current_partition: null,
            last_updated_at: '2026-07-13T11:55:00Z',
        },
    },
}

export const FailedDailyUpdate: Story = {
    args: {
        status: {
            dataset: 'groups',
            readiness_state: 'needs_attention',
            detail: 'A backfill partition failed. Retry the failed warehouse backfill run.',
            completed_partitions: 1,
            total_partitions: 1,
            current_partition: '123456789_2026-07-12',
            last_updated_at: '2026-07-13T11:55:00Z',
        },
    },
}
