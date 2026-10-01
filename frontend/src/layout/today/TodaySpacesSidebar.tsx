import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Fragment } from 'react'

import { IconChat, IconPlus, IconSearch, IconTableOfContents } from '@posthog/icons'
import { Button, Skeleton, Text, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { newSpaceLogic } from 'products/tasks/frontend/spaces/newSpaceLogic'
import { SpacePresenceAvatars } from 'products/tasks/frontend/spaces/SpacePresenceAvatars'

import { TodayPaneSection, TodayPaneSectionProps } from './TodayPaneSection'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'
import { TodayRecentFilterMenu } from './TodayRecentFilterMenu'
import { TodayRecentSearchField } from './TodayRecentSearchField'
import { TodaySessionBulkBar } from './TodaySessionBulkBar'
import { TodaySessionRow } from './TodaySessionRow'
import { selectionClick } from './todaySessionSelection'
import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { TodaySpaceActions } from './TodaySpaceActions'
import { TodaySpaceGlyph } from './TodaySpaceGlyph'
import { TodayWorkSectionId, isLockedSpace, spaceLabel, todaySpacesLogic } from './todaySpacesLogic'
import { TodaySpacesRow } from './TodaySpacesRow'
import { TodayWorkItem } from './todayWorkItems'
import { useTodaySectionLayout } from './useTodaySectionLayout'

export function TodaySpacesSidebar(): JSX.Element {
    const {
        visibleSpaces,
        spacesLoading,
        spacesUnavailable,
        pinnedItems,
        allRecentItems,
        recentItems,
        recentGroups,
        recentSearchVisible,
        recentLoading,
        recentTasksUnavailable,
        collapsedSections,
        unreadSessionIds,
        unreadSpaceIds,
        spacePresence,
        spacePreviews,
    } = useValues(todaySpacesLogic)
    const { loadSpaces, loadRecentTasks, toggleSection, setRecentSearchOpen, clearRecentSearchAndFilters } =
        useActions(todaySpacesLogic)
    const { openNewSpace } = useActions(newSpaceLogic)
    const { selectedSessionIds } = useValues(todaySessionSelectionLogic)
    const { toggleSessionSelection, selectSessionRange, clearSelection } = useActions(todaySessionSelectionLogic)
    const { location, searchParams } = useValues(router)
    const pinnedIds = new Set(pinnedItems.map((item) => item.id))
    const browsingSpaces = location.pathname.endsWith(urls.taskSpaces())
    const selectedIds = new Set(selectedSessionIds)

    // Like Desktop, Cmd/Ctrl-click and Shift-click pick rows instead of opening them, and a plain click clears the pick.
    const onSelectClick = (sessionId: string, event: React.MouseEvent<HTMLElement>): void => {
        const click = selectionClick(event)
        if (click === 'open') {
            clearSelection()
            return
        }
        event.preventDefault()
        event.stopPropagation()
        if (click === 'toggle') {
            toggleSessionSelection(sessionId)
        } else {
            selectSessionRange(sessionId)
        }
    }

    const renderItem = (item: TodayWorkItem, dataAttr: string, inPinnedSection = false): JSX.Element =>
        item.kind === 'session' ? (
            <TodaySessionRow
                key={`${item.kind}-${item.id}`}
                item={item}
                pinned={pinnedIds.has(item.id)}
                showPinBadge={!inPinnedSection}
                dataAttr={dataAttr}
                surface="sidebar"
                unread={unreadSessionIds.has(item.id)}
                selected={selectedIds.has(item.id)}
                onSelectClick={(event) => onSelectClick(item.id, event)}
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
    const notice = (message: string, action: string, onClick: () => void, dataAttr: string): JSX.Element => (
        <div className="flex flex-col items-start gap-2 px-2 py-1">
            <Text size="xs" variant="muted">
                {message}
            </Text>
            <Button variant="outline" size="sm" onClick={onClick} data-attr={dataAttr}>
                {action}
            </Button>
        </div>
    )
    const loadError = (message: string, onRetry: () => void, dataAttr: string): JSX.Element =>
        notice(message, 'Try again', onRetry, dataAttr)

    return (
        <TooltipProvider>
            <div className="TodayPane" data-quill>
                <Button
                    variant="primary"
                    size="lg"
                    className="w-full"
                    render={<LinkPrimitive to={urls.ai()} />}
                    data-attr="today-spaces-new-chat"
                >
                    <IconPlus />
                    New chat
                </Button>
                <div
                    className="mt-6 mb-2 flex min-h-0 flex-1 flex-col overflow-hidden px-1"
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
                            {pinnedItems.map((item) => renderItem(item, 'today-pinned-session', true))}
                        </TodayPaneSection>
                    )}
                    <TodayPaneSection
                        label="Recent"
                        {...sectionLayout('recent')}
                        count={recentItems.length}
                        onToggle={() => toggleSection('recent')}
                        divider={hasPinned}
                        dataAttr="today-section-recent"
                        heading={recentSearchVisible ? <TodayRecentSearchField /> : null}
                        actions={
                            <>
                                {!recentSearchVisible && (
                                    <Tooltip>
                                        <TooltipTrigger
                                            delay={0}
                                            render={
                                                <Button
                                                    size="icon-xs"
                                                    className="text-muted-foreground"
                                                    aria-label="Search recent"
                                                    onClick={() => setRecentSearchOpen(true)}
                                                    data-attr="today-recent-search-open"
                                                />
                                            }
                                        >
                                            <IconSearch />
                                        </TooltipTrigger>
                                        <TooltipContent>Search recent</TooltipContent>
                                    </Tooltip>
                                )}
                                <TodayRecentFilterMenu />
                            </>
                        }
                    >
                        {recentLoading && !allRecentItems.length ? (
                            loadingRows
                        ) : recentTasksUnavailable && !allRecentItems.length ? (
                            loadError('Recent sessions didn’t load.', loadRecentTasks, 'today-recent-retry')
                        ) : !allRecentItems.length ? (
                            <Text size="xs" variant="muted" className="px-2 py-1">
                                Sessions and chats you open show up here.
                            </Text>
                        ) : !recentItems.length ? (
                            notice(
                                'Nothing here matches.',
                                'Clear filters',
                                clearRecentSearchAndFilters,
                                'today-recent-clear-filters'
                            )
                        ) : (
                            <>
                                {recentTasksUnavailable &&
                                    loadError('Some sessions didn’t load.', loadRecentTasks, 'today-recent-retry')}
                                {recentGroups.map((group, index) => (
                                    <Fragment key={group.key}>
                                        {group.label && (
                                            <Text
                                                size="xs"
                                                weight="medium"
                                                variant="muted"
                                                className={cn('block px-2 pb-1', index === 0 ? 'pt-1' : 'pt-3')}
                                            >
                                                {group.label}
                                            </Text>
                                        )}
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
                            <>
                                <Tooltip>
                                    <TooltipTrigger
                                        delay={0}
                                        render={
                                            <Button
                                                size="icon-xs"
                                                className="text-muted-foreground"
                                                aria-label="New space"
                                                onClick={openNewSpace}
                                                data-attr="today-new-space-open-sidebar"
                                            />
                                        }
                                    >
                                        <IconPlus />
                                    </TooltipTrigger>
                                    <TooltipContent>New space</TooltipContent>
                                </Tooltip>
                                <Tooltip>
                                    <TooltipTrigger
                                        delay={0}
                                        render={
                                            <Button
                                                size="icon-xs"
                                                render={<LinkPrimitive to={urls.taskSpaces()} />}
                                                aria-current={browsingSpaces ? 'page' : undefined}
                                                className={cn(
                                                    'text-muted-foreground',
                                                    browsingSpaces && 'bg-fill-selected text-foreground'
                                                )}
                                                aria-label="Browse spaces"
                                                data-attr="today-spaces-browse"
                                            />
                                        }
                                    >
                                        <IconTableOfContents />
                                    </TooltipTrigger>
                                    <TooltipContent>Browse spaces</TooltipContent>
                                </Tooltip>
                            </>
                        }
                    >
                        {spacesLoading && !visibleSpaces.length ? (
                            loadingRows
                        ) : spacesUnavailable ? (
                            loadError('Spaces didn’t load.', loadSpaces, 'today-spaces-retry')
                        ) : (
                            <>
                                {visibleSpaces.map((space) => {
                                    const presence = spacePresence[space.id]
                                    return (
                                        <TodayPreviewTrigger key={space.id} payload={spacePreviews[space.id]}>
                                            <TodaySpacesRow
                                                label={spaceLabel(space)}
                                                icon={
                                                    <TodaySpaceGlyph
                                                        locked={isLockedSpace(space)}
                                                        className="text-muted-foreground"
                                                    />
                                                }
                                                to={urls.taskSpace(space.id)}
                                                active={location.pathname.includes(urls.taskSpace(space.id))}
                                                dataAttr="today-space-row"
                                                action={<TodaySpaceActions space={space} />}
                                                badge={presence ? <SpacePresenceAvatars presence={presence} /> : null}
                                                badgeCount={Math.min(presence?.people.length ?? 1, 3) as 1 | 2 | 3}
                                                unread={unreadSpaceIds.has(space.id)}
                                            />
                                        </TodayPreviewTrigger>
                                    )
                                })}
                                {visibleSpaces.length <= 1 && (
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        className="mt-1 self-start"
                                        data-attr="today-spaces-add"
                                        render={<LinkPrimitive to={urls.taskSpaces()} />}
                                    >
                                        <IconPlus />
                                        Add the spaces you work in
                                    </Button>
                                )}
                            </>
                        )}
                    </TodayPaneSection>
                </div>
                <TodaySessionBulkBar />
            </div>
        </TooltipProvider>
    )
}
