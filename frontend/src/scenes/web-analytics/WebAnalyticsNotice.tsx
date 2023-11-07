import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { IconBugReport, IconFeedback, IconGithub } from 'lib/lemon-ui/icons'

export const WebAnalyticsNotice = (): JSX.Element => {
    const { openSupportForm } = useActions(supportLogic)
    const { preflight } = useValues(preflightLogic)

    const showSupportOptions = preflight?.cloud

    return (
        <LemonBanner type={'info'}>
            <p>PostHog Web Analytics is in closed Alpha. Thanks for taking part! We'd love to hear what you think.</p>
            {showSupportOptions ? (
                <p>
                    <Link onClick={() => openSupportForm('bug')}>
                        <IconBugReport /> Report a bug
                    </Link>{' '}
                    -{' '}
                    <Link onClick={() => openSupportForm('feedback')}>
                        <IconFeedback /> Give feedback
                    </Link>{' '}
                    -{' '}
                    <Link to={'https://github.com/PostHog/posthog/issues/18177'}>
                        <IconGithub /> View GitHub issue
                    </Link>
                </p>
            ) : null}
        </LemonBanner>
    )
}
