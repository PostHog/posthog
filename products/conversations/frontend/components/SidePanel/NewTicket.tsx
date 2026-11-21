import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { MessageInput } from '../Chat/MessageInput'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

export function NewTicket(): JSX.Element {
    const { messageSending, hasNewTicketDraft, supportResponseTime } = useValues(sidepanelTicketsLogic)
    const { sendMessage, setView, updateNewTicketDraft, discardDraft } = useActions(sidepanelTicketsLogic)
    const initialDraft = useMemo(() => sidepanelTicketsLogic.values.newTicketDraft, [])

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
                {hasNewTicketDraft && (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        className="ml-auto"
                        onClick={discardDraft}
                        data-attr="sidebar-discard-ticket-draft"
                    >
                        Discard draft
                    </LemonButton>
                )}
            </div>

            <MessageInput
                onSendMessage={(content, _richContent, _isPrivate, onSuccess) => sendMessage(content, onSuccess)}
                messageSending={messageSending}
                placeholder={placeholder}
                buttonText="Submit ticket"
                minRows={4}
                draftContent={initialDraft}
                onDraftChange={updateNewTicketDraft}
            />
        </div>
    )
}
