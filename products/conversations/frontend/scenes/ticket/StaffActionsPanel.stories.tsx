import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import {
    ImpersonationTicketContext,
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

function Template({ ticketContext }: { ticketContext: ImpersonationTicketContext | null }): JSX.Element {
    const { setTicketContext } = useActions(impersonationNoticeLogic)
    useEffect(() => {
        setTicketContext(ticketContext)
    }, [setTicketContext, ticketContext])
    // Constrain the width to mirror the ticket sidebar, where the login buttons must fit.
    return (
        <div className="max-w-md">
            <StaffActionsPanel />
        </div>
    )
}

// Region can't be inferred (e.g. Slack-opened tickets), so both regions are offered.
export const UnknownRegion: StoryFn = () => (
    <Template ticketContext={{ ticketId: 'abc', email: 'customer@example.com' }} />
)

export const KnownRegion: StoryFn = () => (
    <Template ticketContext={{ ticketId: 'abc', email: 'customer@example.com', region: Region.US }} />
)

export const NoCustomerEmail: StoryFn = () => <Template ticketContext={null} />
