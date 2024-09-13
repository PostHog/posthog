import { Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import defaultLogo from 'public/posthog-logo.svg'
import cloudLogo from 'public/posthog-logo-cloud.svg'
import demoLogo from 'public/posthog-logo-demo.svg'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export function WelcomeLogo({ view }: { view?: string }): JSX.Element {
    const UTM_TAGS = `utm_campaign=in-product&utm_tag=${view || 'welcome'}-header`
    const { preflight } = useValues(preflightLogic)

    return (
        <Link to={`https://posthog.com?${UTM_TAGS}`} className="flex flex-col items-center mb-8">
            <img
                src={preflight?.demo ? demoLogo : preflight?.cloud ? cloudLogo : defaultLogo}
                alt={`PostHog${preflight?.cloud ? ' Cloud' : ''}`}
                className="h-6"
            />
        </Link>
    )
}
