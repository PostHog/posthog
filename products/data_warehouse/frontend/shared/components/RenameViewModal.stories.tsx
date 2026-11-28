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

export const WithRenamePlan: Story = {
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        ...WithKnownReferences.args,
        name: 'orders_by_week',
        plan: {
            name: 'orders_by_week',
            dependents: [
                {
                    id: 'daily-revenue',
                    name: 'daily_revenue',
                    before: 'select day, sum(total) as revenue\nfrom orders_by_day\ngroup by day',
                    after: 'select day, sum(total) as revenue\nfrom orders_by_week\ngroup by day',
                },
            ],
            blocked: [{ id: 'revenue-report', name: 'revenue_report', reason: 'The query does not parse.' }],
            joins: [
                {
                    id: 'orders-customer',
                    field_name: 'customer',
                    source_table_name_before: 'orders_by_day',
                    source_table_name_after: 'orders_by_week',
                    joining_table_name_before: 'customers',
                    joining_table_name_after: 'customers',
                },
            ],
            plan_token: 'token',
        },
    },
}
