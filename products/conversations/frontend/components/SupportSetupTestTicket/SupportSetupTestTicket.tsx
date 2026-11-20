import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { supportSetupCardLogic } from '../SupportSetupCard/supportSetupCardLogic'

export function SupportSetupTestTicket({ preview }: { preview: boolean }): JSX.Element {
    const { testMessage, testTicketLoading, pendingReason } = useValues(supportSetupCardLogic)
    const { setTestMessage, sendTestTicket } = useActions(supportSetupCardLogic)

    // The button and the Enter key share one reason, so neither can send what the other blocks.
    const blockedReason = preview
        ? 'This project already has tickets, so this preview does not send one.'
        : (getAccessControlDisabledReason(AccessControlResourceType.Ticket, AccessControlLevel.Editor) ?? pendingReason)

    return (
        <div className="flex flex-col gap-2 border-t border-primary px-4 py-3">
            <div className="flex flex-col gap-0.5">
                <span className="text-sm font-semibold">See a ticket now</span>
                <span className="text-xs text-secondary">
                    Send a test ticket as a customer and open it in your inbox. It gets the tag "test", and replies to
                    it stay in PostHog.
                </span>
            </div>
            <div className="flex flex-wrap gap-2">
                <LemonInput
                    className="min-w-48 flex-1"
                    value={testMessage}
                    onChange={setTestMessage}
                    onPressEnter={() => !blockedReason && sendTestTicket()}
                    placeholder="Write a message as a customer"
                    maxLength={5000}
                    aria-label="Test ticket message"
                    data-attr="support-setup-test-ticket-message"
                />
                <LemonButton
                    type="primary"
                    loading={testTicketLoading}
                    disabledReason={testTicketLoading ? undefined : (blockedReason ?? undefined)}
                    onClick={() => sendTestTicket()}
                    data-attr="support-setup-test-ticket-send"
                >
                    Send test ticket
                </LemonButton>
            </div>
        </div>
    )
}
