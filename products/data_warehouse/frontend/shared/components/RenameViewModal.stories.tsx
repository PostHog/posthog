import type { Meta, StoryObj } from '@storybook/react'

import { RenameViewModal } from './RenameViewModal'

const meta: Meta<typeof RenameViewModal> = {
    title: 'Scenes-App/Data Warehouse/Rename view modal',
    component: RenameViewModal,
    decorators: [
        (Story) => (
            <div className="bg-default p-4">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof RenameViewModal>

export const WithKnownReferences: Story = {
    args: {
        viewName: 'orders_by_day',
        name: 'orders_by_day',
        nameError: undefined,
        submitError: undefined,
        isSaving: false,
        references: [
            { id: 'daily-revenue', name: 'daily_revenue', type: 'view' },
            { id: 'revenue-report', name: 'revenue_report', type: 'matview' },
            { id: 'orders-endpoint', name: 'orders', type: 'endpoint' },
        ],
        referencesLoading: false,
        referencesError: false,
        inline: true,
        onNameChange: () => undefined,
        onClose: () => undefined,
        onSubmit: () => undefined,
    },
}
