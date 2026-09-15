import { ReactNode } from 'react'

import { Logo } from 'lib/brand'
import { Link } from 'lib/lemon-ui/Link'

/** The bar above a publicly shared canvas or file: what it is on the left, what a viewer can do on the right. */
export function SharedPageHeader({
    title,
    utmCampaign,
    actions,
}: {
    title: ReactNode
    /** Names the surface in the PostHog logo's link, so the click is attributed. */
    utmCampaign: string
    actions?: ReactNode
}): JSX.Element {
    return (
        <header className="SharedPageHeader flex h-12 shrink-0 items-center gap-2 border-b border-primary bg-surface-primary px-4">
            <Link
                to={`https://posthog.com?utm_medium=in-product&utm_campaign=${utmCampaign}`}
                target="_blank"
                className="mr-1 flex shrink-0 items-center"
            >
                <Logo size="xs" />
            </Link>
            <div className="flex min-w-0 flex-1 items-center">{title}</div>
            <div className="flex shrink-0 items-center gap-2">{actions}</div>
        </header>
    )
}
