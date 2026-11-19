import { CardFooter } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'

import type { ContentWidgetFooter } from '../layout/dashboardTypes'

export function ContentTileFooter({
    footer,
    refreshedAt,
}: {
    footer: ContentWidgetFooter
    refreshedAt?: string
}): JSX.Element {
    const updatedAt = footer.showUpdatedAt ? refreshedAt : undefined
    return (
        // The grid's drag cancel selector lists this class, so a tile dragged by its body never starts a drag here.
        <CardFooter className="DashboardV2__footer flex shrink-0 items-center gap-2 min-w-0 text-xs text-secondary">
            <span className="flex-1 min-w-0 truncate">
                {footer.text}
                {footer.text && updatedAt && ' · '}
                {updatedAt && (
                    <>
                        Updated <TZLabel time={updatedAt} />
                    </>
                )}
            </span>
            {footer.link && (
                <Link to={footer.link.url} className="shrink-0" data-attr="dashboard-v2-tile-footer-link">
                    {footer.link.label}
                </Link>
            )}
        </CardFooter>
    )
}
