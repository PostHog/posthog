import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { shareNudgeLogic } from 'scenes/web-analytics/shareNudgeLogic'

export function WebAnalyticsShareColleagueBanner(): JSX.Element | null {
    const { showBanner } = useValues(shareNudgeLogic)
    const { dismissForSession } = useActions(shareNudgeLogic)

    if (!showBanner) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            dismissKey="web-analytics-share-colleague"
            action={{
                children: 'Copy link to share',
                onClick: () => {
                    void copyToClipboard(window.location.href, 'link to share')
                    posthog.capture('web analytics share link copied', { source: 'banner' })
                    dismissForSession()
                },
            }}
        >
            Web analytics is better with your team. Send this view to a colleague.
        </LemonBanner>
    )
}
