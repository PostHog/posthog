import type { Meta, StoryObj } from '@storybook/react'

import type { TicketSidebarWidgetSlots } from '../TicketSidebarWidgets/ticketSidebarLayout'
import { TicketSidebarWidgetsEditor } from './TicketSidebarWidgetsEditor'

const meta: Meta<typeof TicketSidebarWidgetsEditor> = {
    title: 'Scenes-App/Support/TicketSidebarWidgetsEditor',
    component: TicketSidebarWidgetsEditor,
    parameters: { layout: 'padded', viewMode: 'story', testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof TicketSidebarWidgetsEditor>

const placeholder = <div />

// No staff_actions slot, as for a non-staff user. AI triage has nothing to show on this ticket.
const slots: TicketSidebarWidgetSlots = {
    related_groups: { content: placeholder },
    ai_triage: { content: null, unavailableReason: 'AI suggestions are off for this project.' },
    session_recording: { content: placeholder },
    recent_events: { content: placeholder },
    exceptions: { content: placeholder },
    previous_tickets: { content: placeholder },
    activity: { content: placeholder },
}

export const NarrowSidebar: Story = {
    render: () => (
        // The sidebar's minimum width next to the chat.
        <div className="w-[300px]">
            <TicketSidebarWidgetsEditor slots={slots} />
        </div>
    ),
}
