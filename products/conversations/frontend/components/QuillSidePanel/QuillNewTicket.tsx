import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { Button, Heading, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { sidepanelTicketsLogic } from '../SidePanel/sidepanelTicketsLogic'
import { QuillTicketComposer } from './QuillTicketComposer'

export function QuillNewTicket(): JSX.Element {
    const { messageSending, hasNewTicketDraft, supportResponseTime } = useValues(sidepanelTicketsLogic)
    const { sendMessage, setView, updateNewTicketDraft, discardDraft } = useActions(sidepanelTicketsLogic)
    const initialDraft = useMemo(() => sidepanelTicketsLogic.values.newTicketDraft, [])

    const placeholder = supportResponseTime
        ? `Describe what you need help with and our support engineers aim to get back to you within ${supportResponseTime}.`
        : 'Describe what you need help with and our support engineers will get back to you.'

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                size="icon"
                                aria-label="Back to tickets"
                                onClick={() => setView('list')}
                                data-attr="sidebar-go-back-to-tickets"
                            />
                        }
                    >
                        <IconArrowLeft />
                    </TooltipTrigger>
                    <TooltipContent>Back to tickets</TooltipContent>
                </Tooltip>
                <Heading size="sm" render={<h3 className="m-0" />}>
                    New ticket
                </Heading>
                {hasNewTicketDraft && (
                    <Button
                        size="sm"
                        variant="link-muted"
                        className="ml-auto"
                        onClick={discardDraft}
                        data-attr="sidebar-discard-ticket-draft"
                    >
                        Discard draft
                    </Button>
                )}
            </div>
            {/* The draft seeds the editor once. The parent keys this view on the composer revision, so a new
                prefill or a discard remounts it. */}
            <QuillTicketComposer
                onSend={sendMessage}
                sending={messageSending}
                placeholder={placeholder}
                buttonText="Submit ticket"
                minRows={4}
                draftContent={initialDraft}
                onDraftChange={updateNewTicketDraft}
                autoFocus
            />
        </div>
    )
}
