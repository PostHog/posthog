import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { IconBugReport, IconFeedback } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export const WebAnalyticsNotice = (): JSX.Element => {
    const { openSupportForm } = useActions(supportLogic)
    const { preflight } = useValues(preflightLogic)

    const showSupportOptions = preflight?.cloud

    return (
        <LemonBanner type={'info'}>
            <p>PostHog Web Analytics is in opt-in Beta. Thanks for taking part! We'd love to hear what you think.</p>
            {showSupportOptions ? (
                <p>
                    <Link onClick={() => openSupportForm({ kind: 'bug' })}>
                        <IconBugReport /> Report a bug
                    </Link>{' '}
                    -{' '}
                    <Link onClick={() => openSupportForm({ kind: 'feedback' })}>
                        <IconFeedback /> Give feedback
                    </Link>
                </p>
            ) : null}
        </LemonBanner>
    )
}
