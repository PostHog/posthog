import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccountEventStreamMembership } from './AccountEventStreamMembership'
import { eventStreamLogic } from './eventStreamLogic'

// Rendered as flag-gated tab content (AccountNotebooksExpansion), so eventStreamLogic
// only mounts — and only fires its load — when the tab is actually opened.
export function AccountEventStreamToggle({
    accountId,
    externalId,
}: {
    accountId: string
    externalId: string
}): JSX.Element {
    const { settingsUrl } = useValues(eventStreamLogic)

    return (
        <div className="flex flex-col gap-2 items-start">
            <div className="flex items-center gap-1">
                <h4 className="secondary uppercase text-secondary mb-0">Event stream</h4>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconGear />}
                    tooltip="Configure the event stream"
                    data-attr="configure-event-stream"
                    to={settingsUrl}
                />
            </div>
            <AccountEventStreamMembership accountId={accountId} externalId={externalId} />
        </div>
    )
}
