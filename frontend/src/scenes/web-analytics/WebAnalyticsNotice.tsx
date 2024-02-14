import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { IconBugReport, IconFeedback } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export const WebAnalyticsNotice = (): JSX.Element => {
    const { openSupportForm } = useActions(supportLogic)
    const { preflight } = useValues(preflightLogic)

    const showSupportOptions = preflight?.cloud

    return (
        <LemonBanner type="info" className="my-4">
            <div className="flex items-center flex-wrap gap-2 justify-between">
                <div className="flex-1 min-w-full sm:min-w-0">
                    PostHog Web Analytics is in opt-in Beta. Thanks for taking part! We'd love to hear what you think.
                </div>
                {showSupportOptions ? (
                    <span className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            icon={<IconBugReport />}
                            onClick={() => openSupportForm({ kind: 'bug' })}
                        >
                            Report a bug
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            icon={<IconFeedback />}
                            onClick={() => openSupportForm({ kind: 'feedback' })}
                        >
                            Give feedback
                        </LemonButton>
                    </span>
                ) : null}
            </div>
        </LemonBanner>
    )
}
