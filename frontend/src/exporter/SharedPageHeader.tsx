import { ReactNode } from 'react'

import { Logo } from 'lib/brand'
import { Link } from 'lib/lemon-ui/Link'

/** The bar above a publicly shared canvas or file: what it is on the left, what a viewer can do on the right. */
export function SharedPageHeader({
    title,
    description,
    teamName,
    utmCampaign,
    actions,
}: {
    title: string
    description?: string
    teamName?: string
    /** Names the surface in the PostHog logo's link, so the click is attributed. */
    utmCampaign: string
    actions?: ReactNode
}): JSX.Element {
    return (
        <header className="SharedPageHeader flex h-12 shrink-0 items-center gap-3 border-b border-primary bg-surface-primary px-4">
            <Link
                to={`https://posthog.com?utm_medium=in-product&utm_campaign=${utmCampaign}`}
                target="_blank"
                className="flex shrink-0 items-center"
            >
                <Logo size="xs" />
            </Link>
            <div className="flex min-w-0 flex-1 items-baseline gap-2">
                <h1 className="m-0 truncate text-sm font-semibold" title={description || undefined}>
                    {title}
                </h1>
                {description && <span className="hidden truncate text-xs text-muted md:inline">{description}</span>}
            </div>
            <div className="flex shrink-0 items-center gap-3">
                {teamName && <span className="text-xs text-muted">{teamName}</span>}
                {actions}
            </div>
        </header>
    )
}
