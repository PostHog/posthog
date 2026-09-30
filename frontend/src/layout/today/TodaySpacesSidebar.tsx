import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Fragment } from 'react'

import { IconChat, IconList, IconLock, IconPlus } from '@posthog/icons'
import { Button, Skeleton, Text, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger, cn } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { TodayPaneSection, TodayPaneSectionProps } from './TodayPaneSection'
import { TodaySessionRow } from './TodaySessionRow'
import { TodayWorkSectionId, spaceLabel, todaySpacesLogic } from './todaySpacesLogic'
import { TodaySpacesRow } from './TodaySpacesRow'
import { TodayWorkItem } from './todayWorkItems'
import { useTodaySectionLayout } from './useTodaySectionLayout'

export function TodaySpacesSidebar(): JSX.Element {
    const {
        visibleSpaces,
        browsingSpaces,
        spacesLoading,
        spacesUnavailable,
        pinnedItems,
        recentItems,
        recentGroups,
        recentLoading,
        recentTasksUnavailable,
        collapsedSections,
    } = useValues(todaySpacesLogic)
    const { loadSpaces, loadRecentTasks, toggleSection, setBrowsingSpaces } = useActions(todaySpacesLogic)
    const { location, searchParams } = useValues(router)
    const pinnedIds = new Set(pinnedItems.map((item) => item.id))

    const renderItem = (item: TodayWorkItem, dataAttr: string): JSX.Element =>
        item.kind === 'session' ? (
            <TodaySessionRow
                key={`${item.kind}-${item.id}`}
                item={item}
                pinned={pinnedIds.has(item.id)}
                dataAttr={dataAttr}
                surface="sidebar"
            />
        ) : (
            <TodaySpacesRow
                key={`${item.kind}-${item.id}`}
                label={item.title || 'Untitled chat'}
                icon={<IconChat className="text-muted-foreground" />}
                to={urls.ai(item.id)}
                active={location.pathname.endsWith('/ai') && searchParams.chat === item.id}
                dataAttr={dataAttr}
            />
        )

    const hasPinned = pinnedItems.length > 0
    const layoutSections: { id: TodayWorkSectionId; open: boolean }[] = [
        ...(hasPinned ? [{ id: 'pinned' as const, open: !collapsedSections.includes('pinned') }] : []),
        { id: 'recent', open: !collapsedSections.includes('recent') },
        { id: 'spaces', open: !collapsedSections.includes('spaces') },
    ]
    const layout = useTodaySectionLayout(layoutSections)
    const sectionLayout = (
        id: TodayWorkSectionId
    ): Pick<TodayPaneSectionProps, 'open' | 'height' | 'animate' | 'resizer' | 'resizing' | 'contentRef'> => {
        const index = layoutSections.findIndex((section) => section.id === id)
        const section = layoutSections[index]
        const previous = index > 0 ? layoutSections[index - 1] : null
        return {
            open: section.open,
            height: layout.heights[id],
            animate: layout.measured && layout.dragging === null,
            resizer: previous?.open && section.open ? layout.resizer(previous.id, id) : undefined,
            resizing: layout.dragging === id,
            contentRef: layout.measureRefs[id],
        }
    }

    const loadingRows = (
        <div className="flex flex-col gap-2 px-2 py-1">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-2/3" />
        </div>
    )
    const loadError = (message: string, onRetry: () => void, dataAttr: string): JSX.Element => (
        <div className="flex flex-col items-start gap-2 px-2 py-1">
            <Text size="xs" variant="muted">
                {message}
            </Text>
            <Button variant="outline" size="sm" onClick={onRetry} data-attr={dataAttr}>
                Try again
            </Button>
        </div>
    )

    return (
        <TooltipProvider>
            <div className="TodayPane" data-quill>
                <button
                    type="button"
                    className="TodaySidebar__new"
                    data-attr="today-spaces-new-chat"
                    onClick={() => router.actions.push(urls.ai())}
                >
                    <IconPlus />
                    New chat
                </button>
                <div
                    className="mt-4 mb-2 flex min-h-0 flex-1 flex-col overflow-hidden px-1"
                    ref={layout.measureRefs.area}
                >
                    {hasPinned && (
                        <TodayPaneSection
                            label="Pinned"
                            {...sectionLayout('pinned')}
                            count={pinnedItems.length}
                            onToggle={() => toggleSection('pinned')}
                            dataAttr="today-section-pinned"
                        >
                            {pinnedItems.map((item) => renderItem(item, 'today-pinned-session'))}
                        </TodayPaneSection>
                    )}
                    <TodayPaneSection
                        label="Recent"
                        {...sectionLayout('recent')}
                        count={recentItems.length}
                        onToggle={() => toggleSection('recent')}
                        divider={hasPinned}
                        dataAttr="today-section-recent"
                    >
                        {recentLoading && !recentItems.length ? (
                            loadingRows
                        ) : recentTasksUnavailable && !recentItems.length ? (
                            loadError('Recent sessions didn’t load.', loadRecentTasks, 'today-recent-retry')
                        ) : !recentItems.length ? (
                            <Text size="xs" variant="muted" className="px-2 py-1">
                                Sessions and chats you open show up here.
                            </Text>
                        ) : (
                            <>
                                {recentTasksUnavailable &&
                                    loadError('Some sessions didn’t load.', loadRecentTasks, 'today-recent-retry')}
                                {recentGroups.map((group, index) => (
                                    <Fragment key={group.key}>
                                        <Text
                                            size="xs"
                                            variant="muted"
                                            className={cn('block px-2 pb-1', index === 0 ? 'pt-1' : 'pt-3')}
                                        >
                                            {group.label}
                                        </Text>
                                        {group.items.map((item) =>
                                            renderItem(
                                                item,
                                                item.kind === 'chat' ? 'today-recent-chat' : 'today-recent-session'
                                            )
                                        )}
                                    </Fragment>
                                ))}
                            </>
                        )}
                    </TodayPaneSection>
                    <TodayPaneSection
                        label="Spaces"
                        {...sectionLayout('spaces')}
                        count={visibleSpaces.length}
                        onToggle={() => toggleSection('spaces')}
                        divider
                        dataAttr="today-section-spaces"
                        actions={
                            <Tooltip>
                                <TooltipTrigger
                                    delay={0}
                                    render={
                                        <Button
                                            size="icon-sm"
                                            aria-pressed={browsingSpaces}
                                            className={cn(browsingSpaces && 'bg-fill-selected')}
                                            onClick={() => setBrowsingSpaces(!browsingSpaces)}
                                            aria-label={
                                                browsingSpaces ? 'Show starred spaces only' : 'Browse all spaces'
                                            }
                                            data-attr="today-spaces-browse"
                                        />
                                    }
                                >
                                    <IconList />
                                </TooltipTrigger>
                                <TooltipContent>
                                    {browsingSpaces ? 'Show starred spaces only' : 'Browse all spaces'}
                                </TooltipContent>
                            </Tooltip>
                        }
                    >
                        {spacesLoading && !visibleSpaces.length ? (
                            loadingRows
                        ) : spacesUnavailable ? (
                            loadError('Spaces didn’t load.', loadSpaces, 'today-spaces-retry')
                        ) : !visibleSpaces.length && browsingSpaces ? (
                            <Text size="xs" variant="muted" className="px-2 py-1">
                                Spaces group the sessions you and your agents work on. Create one from PostHog Desktop.
                            </Text>
                        ) : (
                            <>
                                {visibleSpaces.map((space) => (
                                    <TodaySpacesRow
                                        key={space.id}
                                        label={spaceLabel(space)}
                                        icon={
                                            space.channel_type === 'private' ? (
                                                <IconLock className="text-muted-foreground" />
                                            ) : (
                                                <span aria-hidden className="font-mono text-muted-foreground">
                                                    #
                                                </span>
                                            )
                                        }
                                        to={urls.taskSpace(space.id)}
                                        active={location.pathname.includes(urls.taskSpace(space.id))}
                                        dataAttr="today-space-row"
                                    />
                                ))}
                                {!browsingSpaces && visibleSpaces.length <= 1 && (
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        className="mt-1 self-start"
                                        data-attr="today-spaces-add"
                                        onClick={() => setBrowsingSpaces(true)}
                                    >
                                        <IconPlus />
                                        Add the spaces you work in
                                    </Button>
                                )}
                            </>
                        )}
                    </TodayPaneSection>
                </div>
            </div>
        </TooltipProvider>
    )
}
