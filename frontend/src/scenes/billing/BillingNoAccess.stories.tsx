import { Meta, StoryObj } from '@storybook/react'

import { BillingNoAccess } from './BillingNoAccess'

const meta: Meta<typeof BillingNoAccess> = {
    title: 'Scenes-Other/Billing/BillingNoAccess',
    component: BillingNoAccess,
    parameters: { layout: 'padded' },
    args: {
        reason: 'This area is restricted to organization admins and up. Your level is member.',
        onRetry: () => {},
        retryLoading: false,
    },
}
export default meta

type Story = StoryObj<typeof BillingNoAccess>

export const Restricted: Story = {}

export const CheckingAgain: Story = { args: { retryLoading: true } }
