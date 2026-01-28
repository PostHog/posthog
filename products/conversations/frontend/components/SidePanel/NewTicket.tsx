import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { MessageInput } from '../Chat/MessageInput'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

export function NewTicket(): JSX.Element {
    const { messageSending } = useValues(sidepanelTicketsLogic)
    const { sendMessage, setView } = useActions(sidepanelTicketsLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <LemonButton
                    icon={<IconArrowLeft />}
                    size="small"
                    onClick={() => setView('list')}
                    data-attr="sidebar-go-back-to-tickets"
                />
                <span className="font-semibold">New ticket</span>
            </div>

            <p className="text-sm text-muted-alt m-0">
                Describe what you need help with and our team will get back to you.
            </p>

            <MessageInput
                onSendMessage={sendMessage}
                messageSending={messageSending}
                placeholder="What can we help you with?"
                buttonText="Submit ticket"
                minRows={4}
            />
        </div>
    )
}
