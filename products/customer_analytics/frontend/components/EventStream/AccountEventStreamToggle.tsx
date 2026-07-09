import { useActions, useValues } from 'kea'

import { LemonSwitch, Link } from '@posthog/lemon-ui'

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
    const settingsUrl = urls.settings('environment-customer-analytics', 'customer-analytics-event-stream')

    return (
        <div className="flex flex-col gap-2 items-start">
            <p className="mb-0 text-secondary">
                Stream this customer's events to your team's Slack channel in real time.
            </p>
            <LemonSwitch
                checked={included}
                onChange={(checked) => setAccountMembership(accountId, checked)}
                disabledReason={
                    !eventStream && !eventStreamLoading
                        ? 'Set up the event stream in settings first'
                        : eventStreamLoading || updating
                          ? 'Updating…'
                          : undefined
                }
                label="Include in event stream"
                size="small"
                bordered
            />
            {included && !externalId ? (
                <span className="text-xs text-secondary">
                    This account has no external ID, so its events can't be matched and won't stream.
                </span>
            ) : null}
            <Link to={settingsUrl} className="text-xs">
                Configure the event stream
            </Link>
        </div>
    )
}
