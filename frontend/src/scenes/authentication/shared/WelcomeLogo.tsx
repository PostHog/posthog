import { Link } from '@posthog/lemon-ui'

import { Logo } from 'lib/brand'

export function WelcomeLogo({ view }: { view?: string }): JSX.Element {
    const UTM_TAGS = `utm_campaign=in-product&utm_tag=${view || 'welcome'}-header`
    const logoHref = `https://posthog.com?${UTM_TAGS}`

    return (
        <Link to={logoHref} className="flex flex-col items-center mb-8" aria-label="posthog.com">
            <Logo size="md" className="shrink-0" aria-hidden />
        </Link>
    )
}
