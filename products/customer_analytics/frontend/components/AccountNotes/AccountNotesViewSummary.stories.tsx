import type { Meta, StoryObj } from '@storybook/react'

import { AccountNotesViewSummary } from './AccountNotesViewSummary'

const meta: Meta<typeof AccountNotesViewSummary> = {
    title: 'Customer Analytics/Saved views/Notes summary',
    component: AccountNotesViewSummary,
    args: {
        scope: 'account',
        state: {
            filters: {
                search: 'renewal',
                tags: ['risk'],
                created_by: [],
                assigned_to: [],
                account_id: 'example-account',
                account_name: 'Example account',
            },
            ordering: 'account_name',
        },
    },
}
export default meta

type Story = StoryObj<typeof AccountNotesViewSummary>
export const Account: Story = {}
export const Team: Story = { args: { scope: 'notes_tab' } }
