import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

export function NewTicket(): JSX.Element {
    const { messageSending, message } = useValues(sidepanelTicketsLogic)
    const { sendMessage, setMessage, setView } = useActions(sidepanelTicketsLogic)

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

            <LemonTextArea
                placeholder="What can we help you with?"
                value={message}
                onChange={setMessage}
                minRows={4}
                disabled={messageSending}
            />

            <LemonButton
                type="primary"
                fullWidth
                center
                onClick={sendMessage}
                loading={messageSending}
                disabled={!message.trim() || messageSending}
                data-attr="sidebar-submit-new-ticket"
            >
                Submit ticket
            </LemonButton>
        </div>
    )
}
