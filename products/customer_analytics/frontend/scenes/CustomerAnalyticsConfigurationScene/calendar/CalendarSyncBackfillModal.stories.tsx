import type { Meta, StoryObj } from '@storybook/react'

import { CalendarSyncBackfillModal } from './CalendarSyncBackfillModal'

const meta: Meta<typeof CalendarSyncBackfillModal> = {
    title: 'Customer analytics/Google account backfill',
    component: CalendarSyncBackfillModal,
    args: {
        isOpen: true,
        startDate: '2026-01-11',
        endDate: '2026-04-10',
        dateError: null,
        isSubmitting: false,
        onStartDateChange: () => undefined,
        onEndDateChange: () => undefined,
        onSubmit: () => undefined,
        onClose: () => undefined,
    },
    parameters: {
        layout: 'fullscreen',
        mockDate: '2026-04-10T12:00:00Z',
    },
}

export default meta

type Story = StoryObj<typeof CalendarSyncBackfillModal>

export const Default: Story = {}

export const InvalidRange: Story = {
    args: {
        startDate: '2026-04-10',
        endDate: '2026-04-09',
        dateError: 'The end date must be on or after the start date.',
    },
}
