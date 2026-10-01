import { Badge, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { VIEW_TYPE_INFO, ViewItem } from './viewsUtils'
import { ViewTypeIcon } from './ViewTypeIcon'

/** One view in the Views list: its type, name and when it last changed. The whole row opens the view. */
export function ViewRow({ view }: { view: ViewItem }): JSX.Element {
    const typeLabel = VIEW_TYPE_INFO[view.type].label
    const meta = [
        view.spaceName && `#${view.spaceName}`,
        view.timestamp && `${view.timestampLabel} ${dayjs(view.timestamp).fromNow()}`,
    ]
        .filter(Boolean)
        .join(' · ')

    return (
        <Item
            variant="pressable"
            size="sm"
            // The app styles every link in its accent color. A whole-row link reads as a row, so it keeps the text color.
            className="text-foreground hover:text-foreground"
            render={<LinkPrimitive to={view.href} data-attr={`views-row-${view.type}`} />}
        >
            <ItemMedia variant="icon" aria-hidden>
                <ViewTypeIcon type={view.type} />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle className="truncate">{view.name}</ItemTitle>
                {meta && (
                    <ItemDescription className="truncate" translate="no">
                        {meta}
                    </ItemDescription>
                )}
            </ItemContent>
            <ItemActions>
                <Badge>{typeLabel}</Badge>
            </ItemActions>
        </Item>
    )
}
