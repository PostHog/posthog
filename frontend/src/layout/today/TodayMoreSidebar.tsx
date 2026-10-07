import { useActions } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@posthog/quill'

import { TODAY_MORE_ITEMS } from './todayRailItems'
import { todayShellLogic } from './todayShellLogic'

export function TodayMoreSidebar(): JSX.Element {
    const { pickPane } = useActions(todayShellLogic)

    return (
        <div className="TodayPane">
            <ItemGroup className="gap-1">
                {TODAY_MORE_ITEMS.map(({ pane, label, Icon, description }) => (
                    <Item
                        key={pane}
                        variant="outline"
                        render={<button type="button" className="w-full cursor-pointer text-left" />}
                        onClick={() => pickPane(pane)}
                        data-attr={`today-more-${pane}`}
                    >
                        <ItemMedia variant="icon">
                            <Icon />
                        </ItemMedia>
                        <ItemContent>
                            <ItemTitle>{label}</ItemTitle>
                            <ItemDescription>{description}</ItemDescription>
                        </ItemContent>
                        <ItemActions>
                            <IconChevronRight className="size-4 text-muted-foreground" />
                        </ItemActions>
                    </Item>
                ))}
            </ItemGroup>
        </div>
    )
}
