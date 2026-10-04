import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Fragment } from 'react'

import { IconPlus, IconTableOfContents } from '@posthog/icons'
import { Button, Skeleton, Text, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { newSpaceLogic } from 'products/tasks/frontend/spaces/newSpaceLogic'
import { SpacePresenceAvatars } from 'products/tasks/frontend/spaces/SpacePresenceAvatars'

import { TodayChatRow } from './TodayChatRow'
import { TodayListAppearanceDialog } from './TodayListAppearanceDialog'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { TodayPaneSection, TodayPaneSectionProps } from './TodayPaneSection'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'
import { TodayRecentFilterMenu } from './TodayRecentFilterMenu'
import { TodaySessionBulkBar } from './TodaySessionBulkBar'
import { TodaySessionRow } from './TodaySessionRow'
import { selectionClick } from './todaySessionSelection'
import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { todayShellLogic } from './todayShellLogic'
import { todayRecentClearLabel, todaySidebarSectionState } from './todaySidebarSectionState'
import { TodaySpaceContextMenu } from './TodaySpaceContextMenu'
import { TodaySpaceGlyph } from './TodaySpaceGlyph'
import { TodayWorkSectionId, isLockedSpace, spaceLabel, todaySpacesLogic } from './todaySpacesLogic'
import { TodaySpacesRow } from './TodaySpacesRow'
import { TodaySpacesSectionTabs } from './TodaySpacesSectionTabs'
import { TodayWorkItem } from './todayWorkItems'
import { useTodaySectionLayout } from './useTodaySectionLayout'

const SKELETON_ROW_WIDTHS = ['w-3/5', 'w-4/5', 'w-2/5'] as const

export function TodaySpacesSidebar(): JSX.Element {
    const {
        visibleSpaces,
        spacesLoading,
        spacesUnavailable,
        pinnedItems,
        shownPinnedItems,
        shownSpaces,
        allRecentItems,
        recentItems,
        recentGroups,
        recentQuery,
        recentFiltersActive,
        recentLoading,
        recentTasksUnavailable,
        collapsedSections,
        unreadSessionIds,
        unreadSpaceIds,
        spacePresence,
        spacePreviews,
        phoneSection,
        pinnedTasksLoading,
    } = useValues(todaySpacesLogic)
    const { loadSpaces, loadRecentTasks, toggleSection, setRecentQuery, clearRecentSearchAndFilters, setPhoneSection } =
        useActions(todaySpacesLogic)
    const { phoneLayout } = useValues(todayShellLogic)
    const { openNewSpace } = useActions(newSpaceLogic)
    const { selectedSessionIds } = useValues(todaySessionSelectionLogic)
    const { toggleSessionSelection, selectSessionRange, clearSelection } = useActions(todaySessionSelectionLogic)
    const { location } = useValues(router)
    const pinnedIds = new Set(pinnedItems.map((item) => item.id))
    const browsingSpaces = location.pathname.endsWith(urls.taskSpaces())
    const selectedIds = new Set(selectedSessionIds)

    // Like Desktop, Cmd/Ctrl-click and Shift-click pick rows instead of opening them, and a plain click clears the pick.
    const onSelectClick = (sessionId: string, event: React.MouseEvent<HTMLElement>): void => {
        if (phoneLayout && selectedIds.size > 0) {
            event.preventDefault()
            event.stopPropagation()
            toggleSessionSelection(sessionId)
            return
        }
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

    // A session can show in more than one group, so the group keeps its rows apart on the keyboard path.
    const optionValue = (group: string, item: TodayWorkItem): string => `${group}:${item.kind}-${item.id}`
    const renderItem = (item: TodayWorkItem, group: string, dataAttr: string, inPinnedSection = false): JSX.Element =>
        item.kind === 'session' ? (
            <TodaySessionRow
                key={`${item.kind}-${item.id}`}
                optionValue={optionValue(group, item)}
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
            <TodayChatRow
                key={`${item.kind}-${item.id}`}
                item={item}
                dataAttr={dataAttr}
                optionValue={optionValue(group, item)}
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

    const recentState = todaySidebarSectionState({
        loading: recentLoading,
        failed: recentTasksUnavailable,
        total: allRecentItems.length,
        shown: recentItems.length,
    })
    const spacesState = todaySidebarSectionState({
        loading: spacesLoading,
        failed: spacesUnavailable,
        total: visibleSpaces.length,
        shown: visibleSpaces.length,
    })

    const loadingRows = (label: string): JSX.Element => (
        <div role="status" aria-label={label} className="flex flex-col gap-px">
            {SKELETON_ROW_WIDTHS.map((width) => (
                <div key={width} aria-hidden className="flex h-7 items-center gap-2 px-2">
                    <Skeleton className="size-3.5 shrink-0 rounded-sm" />
                    <Skeleton className={cn('h-2.5', width)} />
                </div>
            ))}
        </div>
    )
    const notice = (message: string, actions: JSX.Element): JSX.Element => (
        <div className="flex flex-col items-start gap-2 px-2 py-1">
            <Text size="xs" variant="muted">
                {message}
            </Text>
            <div className="flex flex-wrap gap-1">{actions}</div>
        </div>
    )
    const loadError = (message: string, onRetry: () => void, dataAttr: string): JSX.Element =>
        notice(
            message,
            <Button variant="outline" size="sm" onClick={onRetry} data-attr={dataAttr}>
                Try again
            </Button>
        )

    const actionSize = phoneLayout ? 'icon-lg' : 'icon-xs'
    const spacesActions = (
        <>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <Button
                            size={actionSize}
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
                            size={actionSize}
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
    )

    const pinnedRows = shownPinnedItems.map((item) => renderItem(item, 'pinned', 'today-pinned-session', true))

    const recentBody =
        recentState === 'loading' ? (
            loadingRows('Loading recent')
        ) : recentState === 'error' ? (
            loadError('Recent sessions didn’t load.', loadRecentTasks, 'today-recent-retry')
        ) : recentState === 'empty' ? (
            <Text size="xs" variant="muted" className="px-2 py-1">
                Sessions and chats you open show up here. Start one with New chat.
            </Text>
        ) : recentState === 'no-matches' ? (
            notice(
                'No matches',
                <Button
                    variant="outline"
                    size="sm"
                    onClick={clearRecentSearchAndFilters}
                    data-attr="today-recent-clear-filters"
                >
                    {todayRecentClearLabel(recentQuery !== '', recentFiltersActive)}
                </Button>
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
                                'recent',
                                item.kind === 'chat' ? 'today-recent-chat' : 'today-recent-session'
                            )
                        )}
                    </Fragment>
                ))}
            </>
        )

    const spacesBody =
        spacesState === 'loading' ? (
            loadingRows('Loading spaces')
        ) : spacesState === 'error' ? (
            loadError('Spaces didn’t load.', loadSpaces, 'today-spaces-retry')
        ) : spacesState === 'empty' ? (
            notice(
                'Spaces you star show up here.',
                <>
                    <Button variant="outline" size="sm" onClick={openNewSpace} data-attr="today-spaces-empty-new-space">
                        <IconPlus />
                        New space…
                    </Button>
                    <Button
                        variant="outline"
                        size="sm"
                        render={<LinkPrimitive to={urls.taskSpaces()} />}
                        data-attr="today-spaces-add"
                    >
                        Browse spaces
                    </Button>
                </>
            )
        ) : (
            <>
                {spacesUnavailable && loadError('Spaces didn’t refresh.', loadSpaces, 'today-spaces-retry')}
                {shownSpaces.map((space) => {
                    const presence = spacePresence[space.id]
                    return (
                        <TodaySpaceContextMenu key={space.id} space={space}>
                            <TodayPreviewTrigger payload={spacePreviews[space.id]}>
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
                                    optionValue={`space:${space.id}`}
                                    badge={presence ? <SpacePresenceAvatars presence={presence} /> : null}
                                    badgeCount={Math.min(presence?.people.length ?? 1, 3) as 1 | 2 | 3}
                                    unread={unreadSpaceIds.has(space.id)}
                                />
                            </TodayPreviewTrigger>
                        </TodaySpaceContextMenu>
                    )
                })}
                {visibleSpaces.length === 1 && (
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
        )

    if (phoneLayout) {
        const pinnedBody =
            pinnedTasksLoading && pinnedItems.length === 0 ? (
                loadingRows('Loading pinned')
            ) : pinnedItems.length === 0 ? (
                <Text size="sm" variant="muted" className="px-2 py-2">
                    Pinned sessions show up here. To pin a session, press and hold it, then pick Pin.
                </Text>
            ) : shownPinnedItems.length === 0 ? (
                <Text size="sm" variant="muted" className="px-2 py-2">
                    No pinned sessions match your search.
                </Text>
            ) : (
                pinnedRows
            )
        return (
            <TooltipProvider>
                <div className="TodayPane" data-quill>
                    <TodayPaneSearchList
                        query={recentQuery}
                        onQueryChange={setRecentQuery}
                        searchLabel="Search sessions and spaces"
                        dataAttr="today-recent-search"
                        listClassName="mt-1 flex flex-col pb-4"
                    >
                        <TodaySpacesSectionTabs
                            value={phoneSection}
                            onChange={setPhoneSection}
                            counts={{ pinned: pinnedItems.length, spaces: visibleSpaces.length }}
                            actions={
                                phoneSection === 'recent' ? (
                                    <TodayRecentFilterMenu />
                                ) : phoneSection === 'spaces' ? (
                                    spacesActions
                                ) : null
                            }
                        />
                        <div className="flex flex-col gap-px" data-attr={`today-spaces-tab-panel-${phoneSection}`}>
                            {phoneSection === 'pinned'
                                ? pinnedBody
                                : phoneSection === 'recent'
                                  ? recentBody
                                  : spacesBody}
                        </div>
                    </TodayPaneSearchList>
                    <TodaySessionBulkBar />
                    <TodayListAppearanceDialog />
                </div>
            </TooltipProvider>
        )
    }

    return (
        <TooltipProvider>
            <div className="TodayPane" data-quill>
                <TodayPaneSearchList
                    query={recentQuery}
                    onQueryChange={setRecentQuery}
                    searchLabel="Search sessions and spaces"
                    dataAttr="today-recent-search"
                    searchActions={<TodayRecentFilterMenu />}
                    listClassName="flex flex-col overflow-hidden pb-0"
                >
                    <div className="flex min-h-0 flex-1 flex-col overflow-hidden" ref={layout.measureRefs.area}>
                        {hasPinned && (
                            <TodayPaneSection
                                label="Pinned"
                                {...sectionLayout('pinned')}
                                count={pinnedItems.length}
                                onToggle={() => toggleSection('pinned')}
                                dataAttr="today-section-pinned"
                            >
                                {pinnedRows}
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
                            {recentBody}
                        </TodayPaneSection>
                        <TodayPaneSection
                            label="Spaces"
                            {...sectionLayout('spaces')}
                            count={visibleSpaces.length}
                            onToggle={() => toggleSection('spaces')}
                            divider
                            dataAttr="today-section-spaces"
                            actions={spacesActions}
                        >
                            {spacesBody}
                        </TodayPaneSection>
                    </div>
                </TodayPaneSearchList>
                <TodaySessionBulkBar />
                <TodayListAppearanceDialog />
            </div>
        </TooltipProvider>
    )
}
