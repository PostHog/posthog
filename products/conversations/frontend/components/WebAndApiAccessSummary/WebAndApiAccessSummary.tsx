import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { pluralize } from 'lib/utils/strings'

import { signingSecretLogic } from '../../scenes/settings/signingSecretLogic'
import { supportSettingsLogic } from '../../scenes/settings/supportSettingsLogic'
import { QuillWebAndApiAccessSummary } from '../QuillWebAndApiAccessSummary/QuillWebAndApiAccessSummary'
import { WEB_AND_API_ACCESS_ANCHOR_ID } from '../WebAndApiAccessSettings/webAndApiAccessAnchor'

export function WebAndApiAccessSummary(): JSX.Element {
    const { conversationsDomains } = useValues(supportSettingsLogic)
    const { signingSecret } = useValues(signingSecretLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const domainsSummary =
        conversationsDomains.length === 0
            ? 'All domains are allowed.'
            : `${pluralize(conversationsDomains.length, 'allowed domain')}.`
    const secretSummary = signingSecret
        ? signingSecret.secret
            ? 'The identity verification secret is set.'
            : 'No identity verification secret yet.'
        : null
    const scrollToSettings = (): void => document.getElementById(WEB_AND_API_ACCESS_ANCHOR_ID)?.scrollIntoView()

    if (todayRailNav) {
        return (
            <QuillWebAndApiAccessSummary
                domainsSummary={domainsSummary}
                secretSummary={secretSummary}
                onManage={scrollToSettings}
            />
        )
    }

    return (
        <LemonBanner
            type="info"
            action={{
                children: 'Manage',
                onClick: scrollToSettings,
                'data-attr': 'support-web-and-api-access-manage',
            }}
        >
            <span>{domainsSummary}</span>{' '}
            {secretSummary && (
                <>
                    <span>{secretSummary}</span>{' '}
                </>
            )}
            <span>These settings apply to the widget and the Direct API.</span>
        </LemonBanner>
    )
}
