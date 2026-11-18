import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { eventStreamLogic } from './eventStreamLogic'

export function AccountEventStreamSetupBanner(): JSX.Element | null {
    const { eventStream, eventStreamLoading, eventStreamLoadFailed, settingsUrl } = useValues(eventStreamLogic)
    const { loadEventStream } = useActions(eventStreamLogic)

    if (eventStreamLoading || eventStream?.enabled) {
        return null
    }

    if (eventStreamLoadFailed) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: loadEventStream,
                    'data-attr': 'account-event-stream-retry',
                }}
            >
                Couldn't load your event stream. Try again, and if it keeps happening, contact support.
            </LemonBanner>
        )
    }

    return (
        <LemonBanner
            type="info"
            action={{
                children: 'Go to settings',
                to: settingsUrl,
                'data-attr': 'account-event-stream-setup',
            }}
        >
            {eventStream
                ? 'Your event stream is turned off. Turn it on in settings to send events to Slack.'
                : "You haven't set up your event stream yet. Set it up in settings to send events to Slack."}
        </LemonBanner>
    )
}
