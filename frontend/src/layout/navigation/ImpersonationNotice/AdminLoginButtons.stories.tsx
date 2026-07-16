import type { Meta, StoryObj } from '@storybook/react'

import { Region } from '~/types'

import { AdminLoginButtons } from './AdminLoginButtons'

const meta: Meta<typeof AdminLoginButtons> = {
    title: 'Layout/Admin login buttons',
    component: AdminLoginButtons,
    args: {
        ticketContext: {
            ticketId: 'ticket-1',
            email: 'customer.with.a.long.email@example.com',
        },
        adminLoginUrls: [
            { region: Region.US, url: 'https://us.posthog.com/admin/posthog/user/' },
            { region: Region.EU, url: 'https://eu.posthog.com/admin/posthog/user/' },
        ],
    },
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
}
export default meta
type Story = StoryObj<typeof AdminLoginButtons>

export const DefaultLabels: Story = {
    render: (args) => (
        <div className="w-[360px]">
            <AdminLoginButtons {...args} />
        </div>
    ),
}

export const NoCustomerEmail: Story = {
    args: {
        ticketContext: null,
        adminLoginUrls: [],
    },
}
