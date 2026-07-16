import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import {
    type ImpersonationTicketContext,
    impersonationNoticeLogic,
} from '~/layout/navigation/ImpersonationNotice/impersonationNoticeLogic'
import { Region } from '~/types'

import { StaffActionsPanel } from './StaffActionsPanel'

const meta: Meta<typeof StaffActionsPanel> = {
    title: 'Scenes-App/Conversations/Staff Actions Panel',
    component: StaffActionsPanel,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
}
export default meta
type Story = StoryObj<typeof StaffActionsPanel>

// The panel reads the ticket context from impersonationNoticeLogic, so each story
// mounts the logic and seeds the context it wants to render.
function PanelWithContext({ context }: { context: ImpersonationTicketContext | null }): JSX.Element {
    const { setTicketContext } = useActions(impersonationNoticeLogic)
    useMountedLogic(impersonationNoticeLogic)

    useEffect(() => {
        setTicketContext(context)
        return () => setTicketContext(null)
    }, [context, setTicketContext])

    return (
        <div className="w-[300px]">
            <StaffActionsPanel />
        </div>
    )
}

export const KnownRegion: Story = {
    render: () => (
        <PanelWithContext context={{ ticketId: 'ticket-1', email: 'customer@example.com', region: Region.US }} />
    ),
}

export const AmbiguousRegion: Story = {
    render: () => (
        <PanelWithContext context={{ ticketId: 'ticket-2', email: 'customer.with.a.long.email@example.com' }} />
    ),
}

export const NoCustomerEmail: Story = {
    render: () => <PanelWithContext context={{ ticketId: 'ticket-3', email: '' }} />,
}
