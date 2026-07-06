import { useActions, useValues } from 'kea'

import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { eventStreamLogic } from './eventStreamLogic'

interface AccountEventStreamToggleProps {
    accountId: string
    externalId: string
}

export function AccountEventStreamToggle(props: AccountEventStreamToggleProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    // Gate before the inner component so eventStreamLogic never mounts (and never
    // fires its load request) when the feature is off.
    if (!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_EVENT_STREAM]) {
        return null
    }
    return <AccountEventStreamToggleContent {...props} />
}

function AccountEventStreamToggleContent({ accountId, externalId }: AccountEventStreamToggleProps): JSX.Element {
    const { eventStream, eventStreamLoading, membershipUpdatingIds, isAccountInStream } = useValues(eventStreamLogic)
    const { setAccountMembership } = useActions(eventStreamLogic)

    const included = isAccountInStream(accountId)
    const updating = membershipUpdatingIds.includes(accountId)
    const settingsUrl = urls.settings('environment-customer-analytics', 'customer-analytics-event-stream')

    return (
        <div className="flex flex-col gap-1 mt-4">
            <h4 className="secondary uppercase text-secondary mb-0">Event stream</h4>
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
