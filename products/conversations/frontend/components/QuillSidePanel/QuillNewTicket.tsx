import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { Button, Heading, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { sidepanelTicketsLogic } from '../SidePanel/sidepanelTicketsLogic'
import { QuillTicketComposer } from './QuillTicketComposer'

export function QuillNewTicket(): JSX.Element {
    const { messageSending, newTicketDraft, supportResponseTime } = useValues(sidepanelTicketsLogic)
    const { sendMessage, setView } = useActions(sidepanelTicketsLogic)

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
            </div>
            {/* The draft seeds the editor once. The parent keys this view on the draft revision, so a new prefill
                remounts it. */}
            <QuillTicketComposer
                onSend={sendMessage}
                sending={messageSending}
                placeholder={placeholder}
                buttonText="Submit ticket"
                minRows={4}
                draftContent={newTicketDraft}
                autoFocus
            />
        </div>
    )
}
