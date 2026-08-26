import type { Meta, StoryObj } from '@storybook/react'

import type { TicketViewer } from './ticketPresence'
import { TicketViewers } from './TicketViewers'

const meta: Meta<typeof TicketViewers> = {
    title: 'Scenes-App/Support/TicketViewers',
    component: TicketViewers,
    parameters: { layout: 'padded', viewMode: 'story' },
}
export default meta

type Story = StoryObj<typeof TicketViewers>

const viewers: TicketViewer[] = [
    { id: 1, email: 'alice@example.com', first_name: 'Alice', last_name: 'Ames' },
    { id: 2, email: 'bob@example.com', first_name: 'Bob', last_name: 'Bell' },
    { id: 3, email: 'carol@example.com', first_name: 'Carol' },
    { id: 4, email: 'dan@example.com', first_name: '' },
]

export const OneViewer: Story = {
    args: { viewers: viewers.slice(0, 1) },
}

export const AlsoViewingOnTicketPage: Story = {
    args: { viewers: viewers.slice(0, 2), also: true },
}

export const OverflowingQueueCell: Story = {
    args: { viewers },
}
