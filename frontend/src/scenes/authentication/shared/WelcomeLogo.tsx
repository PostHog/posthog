import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { PostHogWordmarkLogo } from 'lib/brand/PostHogWordmarkLogo'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import demoLogo from 'public/posthog-logo-demo.svg'

export function WelcomeLogo({ view }: { view?: string }): JSX.Element {
    const UTM_TAGS = `utm_campaign=in-product&utm_tag=${view || 'welcome'}-header`
    const { preflight } = useValues(preflightLogic)

    const altText = `PostHog${preflight?.cloud ? ' Cloud' : ''}`
    const logoHref = `https://posthog.com?${UTM_TAGS}`

    return (
        <Link to={logoHref} className="flex flex-col items-center mb-8" aria-label={altText}>
            <span className="flex items-center gap-2">
                {preflight?.demo ? (
                    <img src={demoLogo} alt="" className="h-6" aria-hidden />
                ) : (
                    <PostHogWordmarkLogo className="h-6 w-auto shrink-0 text-primary" aria-hidden />
                )}
                {preflight?.cloud && !preflight?.demo && (
                    <span className="text-primary text-xl font-bold leading-none" aria-hidden>
                        Cloud
                    </span>
                )}
            </span>
        </Link>
    )
}
