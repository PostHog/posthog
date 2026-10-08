import { useMemo } from 'react'

import { IconGitRepository } from '@posthog/icons'
import { Item, ItemActions, ItemContent, ItemDescription, ItemSeparator, ItemTitle, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { SpacePresenceAvatars } from 'products/tasks/frontend/spaces/SpacePresenceAvatars'

import { cardMenuParts } from './todayMenuParts'
import { TodaySpaceKind, TodaySpacePreview } from './todayPreviewCards'
import { TodaySpaceActions } from './TodaySpaceActions'
import { TodaySpaceGlyph } from './TodaySpaceGlyph'

const KIND_LABELS: Record<TodaySpaceKind, string> = {
    public: 'Space',
    private: 'Private space',
    personal: 'Personal space',
}

// A space's actions open no submenu, so nothing has to hold the card open.
const NO_SUBMENU = (): void => {}

/**
 * A space row's hover card: what kind of space it is, who works in it, which repositories it uses, and its actions.
 * Like PostHog Desktop, the row itself carries no buttons, so New session leads the list here.
 */
export function TodaySpaceHoverCard({
    preview,
    onAction,
}: {
    preview: TodaySpacePreview
    /** Closes the card once an action is chosen. */
    onAction: () => void
}): JSX.Element {
    const parts = useMemo(() => cardMenuParts(onAction, NO_SUBMENU), [onAction])
    return (
        <div className="flex flex-col" data-attr="today-space-hover-card">
            {/* `flex-nowrap` keeps the faces beside a long name. */}
            <Item size="xs" className="flex-nowrap items-start">
                <ItemContent className="min-w-0">
                    {/* `wrap-anywhere`: the title sizes to its content, so a long name would widen the card. */}
                    <ItemTitle className="flex items-center gap-2 wrap-anywhere">
                        <span className="flex size-3.5 shrink-0 items-center justify-center text-muted-foreground">
                            <TodaySpaceGlyph locked={preview.spaceKind !== 'public'} />
                        </span>
                        <span className="min-w-0 font-semibold">{preview.name}</span>
                        {preview.unreadSessions > 0 && (
                            <span aria-hidden className="size-2 shrink-0 rounded-full bg-primary" />
                        )}
                    </ItemTitle>
                    <ItemDescription className="pl-5.5">
                        <span className="block">{KIND_LABELS[preview.spaceKind]}</span>
                        {preview.lastActivityAt && (
                            <span className="block">{`Active ${dayjs(preview.lastActivityAt).fromNow()}`}</span>
                        )}
                    </ItemDescription>
                </ItemContent>
                <ItemActions className="self-start">
                    <SpacePresenceAvatars
                        presence={{ people: preview.people, liveUuids: preview.liveUuids }}
                        creatorUuid={preview.creatorUuid}
                    />
                </ItemActions>
            </Item>
            {(preview.unreadSessions > 0 || preview.repositories.length > 0) && (
                <>
                    <ItemSeparator className="my-0" />
                    <Item size="xs">
                        <ItemContent className="min-w-0 gap-1.5">
                            {preview.unreadSessions > 0 && (
                                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                                    <span aria-hidden className="size-2 shrink-0 rounded-full bg-primary" />
                                    {`${preview.unreadSessions} unread`}
                                </span>
                            )}
                            {preview.repositories.length > 0 && (
                                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                                    {preview.repositories.map((repository) => (
                                        <span
                                            key={repository}
                                            className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground"
                                        >
                                            <IconGitRepository className="size-3 shrink-0" />
                                            <span className="truncate">{repository}</span>
                                        </span>
                                    ))}
                                    {preview.hiddenRepositoryCount > 0 && (
                                        <Text size="xs" variant="muted" render={<span />}>
                                            {`+${preview.hiddenRepositoryCount} more`}
                                        </Text>
                                    )}
                                </div>
                            )}
                        </ItemContent>
                    </Item>
                </>
            )}
            <ItemSeparator className="my-0" />
            <div className="flex flex-col p-1">
                <TodaySpaceActions parts={parts} space={preview.space} dataAttrPrefix="today-space-card" />
            </div>
        </div>
    )
}
