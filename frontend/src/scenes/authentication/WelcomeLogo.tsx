import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import cloudLogo from 'public/posthog-logo-cloud.svg'
import demoLogo from 'public/posthog-logo-demo.svg'
import defaultLogo from 'public/posthog-logo.svg'
import twigLogo from 'public/twig-logo.svg'

export function WelcomeLogo({ view }: { view?: string }): JSX.Element {
    const UTM_TAGS = `utm_campaign=in-product&utm_tag=${view || 'welcome'}-header`
    const { preflight } = useValues(preflightLogic)
    const isTwig = preflight?.auth_brand === 'twig'

    const logoSrc = isTwig ? twigLogo : preflight?.demo ? demoLogo : preflight?.cloud ? cloudLogo : defaultLogo
    const altText = isTwig ? 'Twig' : `PostHog${preflight?.cloud ? ' Cloud' : ''}`
    const logoHref = isTwig ? 'https://twig.com' : `https://posthog.com?${UTM_TAGS}`

    return (
        <Link to={logoHref} className="flex flex-col items-center mb-8">
            <img src={logoSrc} alt={altText} className="h-6" />
        </Link>
    )
}
