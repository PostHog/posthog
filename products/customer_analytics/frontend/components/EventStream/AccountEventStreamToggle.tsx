import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

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
    const { eventStream, eventStreamLoading, membershipUpdatingIds, isAccountInStream } = useValues(eventStreamLogic)
    const { setAccountMembership } = useActions(eventStreamLogic)

    const included = isAccountInStream(accountId)
    const updating = membershipUpdatingIds.includes(accountId)

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
                    to={urls.customerAnalyticsConfiguration('customer-analytics-event-stream')}
                />
            </div>
            <p className="mb-0 text-secondary">Stream this customer's events to your Slack channel in real time.</p>
            <LemonSwitch
                checked={included}
                onChange={(checked) => setAccountMembership(accountId, checked)}
                disabledReason={
                    !eventStream && !eventStreamLoading
                        ? 'Set up your event stream in settings first'
                        : eventStreamLoading || updating
                          ? 'Updating…'
                          : undefined
                }
                label="Include in my event stream"
                size="small"
                bordered
            />
            {included && !externalId ? (
                <span className="text-xs text-secondary">
                    This account has no external ID, so its events can't be matched and won't stream.
                </span>
            ) : null}
        </div>
    )
}
