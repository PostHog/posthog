import { CardFooter } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'

import type { TileFooterItem } from '../layout/dashboardTypes'

function FooterItem({ item, refreshedAt }: { item: TileFooterItem; refreshedAt?: string }): JSX.Element {
    switch (item.type) {
        case 'text':
            return <span className="min-w-0 truncate">{item.text}</span>
        case 'updatedAt':
            return (
                <span className="shrink-0">
                    {refreshedAt ? (
                        <>
                            Updated <TZLabel time={refreshedAt} />
                        </>
                    ) : (
                        'Not refreshed yet'
                    )}
                </span>
            )
        case 'link':
            return (
                <Link to={item.url} className="shrink-0" data-attr="dashboard-v2-tile-footer-link">
                    {item.label}
                </Link>
            )
    }
}

export function ContentTileFooter({
    items,
    refreshedAt,
}: {
    items: TileFooterItem[]
    refreshedAt?: string
}): JSX.Element {
    return (
        // The grid's drag cancel selector lists this class, so a tile dragged by its body never starts a drag here.
        <CardFooter className="DashboardV2__footer flex shrink-0 items-center gap-2 min-w-0 text-xs text-secondary">
            {items.map((item, index) => (
                <FooterItem key={index} item={item} refreshedAt={refreshedAt} />
            ))}
        </CardFooter>
    )
}
