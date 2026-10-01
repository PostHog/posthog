import { Item, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { VIEW_TYPE_INFO, ViewItem } from './viewsUtils'
import { ViewTypeIcon } from './ViewTypeIcon'

/** One view in the Views list: its type, name, space and when it last changed. The whole row opens the view. */
export function ViewRow({ view }: { view: ViewItem }): JSX.Element {
    const meta = [
        VIEW_TYPE_INFO[view.type].label,
        view.spaceName && `#${view.spaceName}`,
        view.timestamp && `${view.timestampLabel} ${dayjs(view.timestamp).fromNow()}`,
    ]
        .filter(Boolean)
        .join(' · ')

    return (
        <Item
            variant="outline"
            size="sm"
            // The app styles every link in its accent color. A whole-row link reads as a row, so it keeps the text color.
            className="text-foreground hover:bg-fill-button-tertiary-hover hover:text-foreground"
            render={<LinkPrimitive to={view.href} data-attr={`views-row-${view.type}`} />}
        >
            <ItemMedia variant="icon" aria-hidden>
                <ViewTypeIcon type={view.type} />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle className="truncate">{view.name}</ItemTitle>
                <ItemDescription className="truncate">{meta}</ItemDescription>
            </ItemContent>
        </Item>
    )
}
