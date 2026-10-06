import { Item, ItemContent, ItemDescription, ItemMedia, ItemTitle, Spinner } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPE_INFO, AnalyticsItem, analyticsOpenHref } from './analyticsUtils'

interface AnalyticsRowProps {
    analytics: AnalyticsItem
    /** A canvas whose first build is still running, so the row shows a spinner in place of its icon. */
    building?: boolean
    /** Where the opened page sends the person back to. Without it, the page's own list. */
    backUrl?: string
    dataAttr: string
}

export function AnalyticsRow({ analytics, building = false, backUrl, dataAttr }: AnalyticsRowProps): JSX.Element {
    const meta = [
        ANALYTICS_TYPE_INFO[analytics.type].label,
        analytics.spaceName && `#${analytics.spaceName}`,
        building
            ? 'Building'
            : analytics.timestamp && `${analytics.timestampLabel} ${dayjs(analytics.timestamp).fromNow()}`,
    ]
        .filter(Boolean)
        .join(' · ')

    return (
        <Item
            variant="outline"
            size="sm"
            // The app styles every link in its accent color. A whole-row link reads as a row, so it keeps the text color.
            className="text-foreground hover:bg-fill-button-tertiary-hover hover:text-foreground"
            render={
                <LinkPrimitive
                    to={backUrl ? analyticsOpenHref(analytics, backUrl) : analytics.href}
                    data-attr={dataAttr}
                />
            }
        >
            <ItemMedia variant="icon" aria-hidden>
                {building ? <Spinner /> : <AnalyticsTypeIcon type={analytics.type} />}
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle className="truncate">{analytics.name}</ItemTitle>
                <ItemDescription className="truncate" translate="no">
                    {meta}
                </ItemDescription>
            </ItemContent>
        </Item>
    )
}
