import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { MessageInput } from '../Chat/MessageInput'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

export function NewTicket(): JSX.Element {
    const { messageSending, newTicketDraft, supportResponseTime } = useValues(sidepanelTicketsLogic)
    const { sendMessage, setView } = useActions(sidepanelTicketsLogic)

    const placeholder = supportResponseTime
        ? `Describe what you need help with and our support engineers aim to get back to you within ${supportResponseTime}.`
        : 'Describe what you need help with and our support engineers will get back to you.'

    return (
        <div className="flex flex-col">
            <div className="flex items-center gap-2">
                <LemonButton
                    icon={<IconArrowLeft />}
                    size="small"
                    onClick={() => setView('list')}
                    data-attr="sidebar-go-back-to-tickets"
                />
                <span className="font-semibold">New ticket</span>
            </div>

            {/* draftContent seeds the editor from a prefilled CTA; no onDraftChange, since routing
                typing back through the logic (which keys this component) would remount on every
                keystroke and drop focus. The draft is a one-shot initial value. */}
            <MessageInput
                onSendMessage={(content, _richContent, _isPrivate, onSuccess) => sendMessage(content, onSuccess)}
                messageSending={messageSending}
                placeholder={placeholder}
                buttonText="Submit ticket"
                minRows={4}
                draftContent={newTicketDraft}
            />
        </div>
    )
}
