import { Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import cloudLogoDark from 'public/posthog-logo-cloud-dark.svg'
import cloudLogoLight from 'public/posthog-logo-cloud-light.svg'
import defaultLogoDark from 'public/posthog-logo-dark.svg'
import demoLogoDark from 'public/posthog-logo-demo-dark.svg'
import demoLogoLight from 'public/posthog-logo-demo-light.svg'
import defaultLogoLight from 'public/posthog-logo-light.svg'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function WelcomeLogo({ view }: { view?: string }): JSX.Element {
    const UTM_TAGS = `utm_campaign=in-product&utm_tag=${view || 'welcome'}-header`
    const { preflight } = useValues(preflightLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    let logoSrc: any
    if (preflight?.demo) {
        logoSrc = isDarkModeOn ? demoLogoDark : demoLogoLight
    } else if (preflight?.cloud) {
        logoSrc = isDarkModeOn ? cloudLogoDark : cloudLogoLight
    } else {
        logoSrc = isDarkModeOn ? defaultLogoDark : defaultLogoLight
    }

    return (
        <Link to={`https://posthog.com?${UTM_TAGS}`}>
            <div className="header-logo">
                <img src={logoSrc} alt={`PostHog${preflight?.cloud ? ' Cloud' : ''}`} />
            </div>
        </Link>
    )
}
