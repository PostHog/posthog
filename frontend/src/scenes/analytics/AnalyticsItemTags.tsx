import { useActions, useValues } from 'kea'

import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuTrigger,
    Text,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { isTaggableAnalyticsType } from './analyticsFeed'
import { analyticsListLogic } from './analyticsListLogic'
import { AnalyticsTagIcon } from './AnalyticsTagIcon'
import { analyticsTagsLogic } from './analyticsTagsLogic'
import { AnalyticsItem, analyticsItemTarget } from './analyticsUtils'

/** While the list is filtered by one of the row's tags, the chip names that tag, so the reason the row matched stays visible. */
export function AnalyticsItemTags({ item }: { item: AnalyticsItem }): JSX.Element | null {
    const { filters } = useValues(analyticsListLogic)
    const { setFilters } = useActions(analyticsListLogic)
    const { openTagEditor } = useActions(analyticsTagsLogic)
    const { type, tags } = item
    if (!isTaggableAnalyticsType(type) || !tags.length) {
        return null
    }
    const filtered = tags.find((tag) => filters.tags.includes(tag))
    const toggle = (tag: string): void =>
        setFilters({
            tags: filters.tags.includes(tag) ? filters.tags.filter((other) => other !== tag) : [...filters.tags, tag],
        })

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        size="xs"
                        aria-label={pluralize(tags.length, 'tag')}
                        className="max-w-48 shrink-0 gap-1 px-1.5"
                        data-attr="analytics-list-row-tags"
                    />
                }
            >
                <AnalyticsTagIcon />
                {filtered ? (
                    <>
                        <span className="min-w-0 truncate">{filtered}</span>
                        {tags.length > 1 && (
                            <span className="shrink-0 text-muted-foreground">{`+${tags.length - 1}`}</span>
                        )}
                    </>
                ) : (
                    <span>{tags.length}</span>
                )}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-56 max-w-80">
                <DropdownMenuGroup>
                    <div className="flex items-center justify-between gap-2">
                        <DropdownMenuLabel>{pluralize(tags.length, 'tag')}</DropdownMenuLabel>
                        <DropdownMenuItem
                            className="w-auto shrink-0"
                            onClick={() => openTagEditor({ ...analyticsItemTarget(item), type })}
                            data-attr="analytics-list-row-tags-manage"
                        >
                            Manage
                        </DropdownMenuItem>
                    </div>
                    {tags.map((tag) => {
                        const active = filters.tags.includes(tag)
                        return (
                            <DropdownMenuItem key={tag} onClick={() => toggle(tag)} data-attr="analytics-list-row-tag">
                                <AnalyticsTagIcon className="size-3.5" />
                                <span className="min-w-0 flex-1 break-all text-left">{tag}</span>
                                <Text size="xs" variant="muted" className="ml-2 shrink-0">
                                    {active ? 'Remove filter' : 'Filter'}
                                </Text>
                            </DropdownMenuItem>
                        )
                    })}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
