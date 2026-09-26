import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { eventStreamLogic } from './eventStreamLogic'

export function AccountEventStreamMembership({
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
                data-attr="account-event-stream-membership"
            />
            {included && !externalId ? (
                <span className="text-xs text-secondary">
                    This account has no external ID, so its events can't be matched and won't stream.
                </span>
            ) : null}
        </div>
    )
}
