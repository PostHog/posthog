import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { signingSecretLogic } from '../../scenes/settings/signingSecretLogic'
import { supportSettingsLogic } from '../../scenes/settings/supportSettingsLogic'
import { WEB_AND_API_ACCESS_ANCHOR_ID } from '../WebAndApiAccessSettings/webAndApiAccessAnchor'

export function WebAndApiAccessSummary(): JSX.Element {
    const { conversationsDomains } = useValues(supportSettingsLogic)
    const { signingSecret } = useValues(signingSecretLogic)

    const domainsSummary =
        conversationsDomains.length === 0
            ? 'All domains are allowed.'
            : `${pluralize(conversationsDomains.length, 'allowed domain')}.`

    return (
        <LemonBanner
            type="info"
            action={{
                children: 'Manage',
                onClick: () => document.getElementById(WEB_AND_API_ACCESS_ANCHOR_ID)?.scrollIntoView(),
                'data-attr': 'support-web-and-api-access-manage',
            }}
        >
            <span>{domainsSummary}</span>{' '}
            {signingSecret && (
                <>
                    <span>
                        {signingSecret.secret
                            ? 'The identity verification secret is set.'
                            : 'No identity verification secret yet.'}
                    </span>{' '}
                </>
            )}
            <span>These settings apply to the widget and the Direct API.</span>
        </LemonBanner>
    )
}
