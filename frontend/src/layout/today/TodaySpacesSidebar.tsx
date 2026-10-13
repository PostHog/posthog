import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { Button, Skeleton, Text, TooltipProvider, cn } from '@posthog/quill'

import { TodayChatRow } from './TodayChatRow'
import { TodayListAppearanceDialog } from './TodayListAppearanceDialog'
import { TodayPaneGroupLabel } from './TodayPaneGroupLabel'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { TodayPaneSection, TodayPaneSectionProps } from './TodayPaneSection'
import { TodayRecentFilterMenu } from './TodayRecentFilterMenu'
import { TodaySessionBulkBar } from './TodaySessionBulkBar'
import { TodaySessionRow } from './TodaySessionRow'
import { selectionClick } from './todaySessionSelection'
import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { todayShellLogic } from './todayShellLogic'
import { todayRecentClearLabel, todaySidebarSectionState } from './todaySidebarSectionState'
import { TodayWorkSectionId, todaySpacesLogic } from './todaySpacesLogic'
import { TodaySpacesSectionTabs } from './TodaySpacesSectionTabs'
import { TodayWorkItem } from './todayWorkItems'
import { useTodaySectionLayout } from './useTodaySectionLayout'

const SKELETON_ROW_WIDTHS = ['w-3/5', 'w-4/5', 'w-2/5'] as const

export function TodaySpacesSidebar(): JSX.Element {
    const {
        pinnedItems,
        shownPinnedItems,
        allRecentItems,
        recentItems,
        recentGroups,
        recentQuery,
        recentFiltersActive,
        recentLoading,
        recentTasksUnavailable,
        collapsedSections,
        unreadSessionIds,
        phoneSection,
        pinnedTasksLoading,
    } = useValues(todaySpacesLogic)
    const { loadRecentTasks, toggleSection, setRecentQuery, clearRecentSearchAndFilters, setPhoneSection } =
        useActions(todaySpacesLogic)
    const { phoneLayout } = useValues(todayShellLogic)
    const { selectedSessionIds } = useValues(todaySessionSelectionLogic)
    const { toggleSessionSelection, selectSessionRange, clearSelection } = useActions(todaySessionSelectionLogic)
    const pinnedIds = new Set(pinnedItems.map((item) => item.id))
    const shownSection: TodayWorkSectionId = phoneSection === 'pinned' ? 'pinned' : 'recent'
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

    const pinnedRows = shownPinnedItems.map((item) => renderItem(item, 'pinned', 'today-pinned-session', true))

    const recentBody =
        recentState === 'loading' ? (
            loadingRows('Loading recent')
        ) : recentState === 'error' ? (
            loadError('Recent chats didn’t load.', loadRecentTasks, 'today-recent-retry')
        ) : recentState === 'empty' ? (
            <Text size="xs" variant="muted" className="px-2 py-1">
                Chats you start show up here. Start one with New chat.
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
                {recentTasksUnavailable && loadError('Some chats didn’t load.', loadRecentTasks, 'today-recent-retry')}
                {recentGroups.map((group, index) => (
                    <Fragment key={group.key}>
                        {group.label && <TodayPaneGroupLabel first={index === 0}>{group.label}</TodayPaneGroupLabel>}
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

    if (phoneLayout) {
        const pinnedBody =
            pinnedTasksLoading && pinnedItems.length === 0 ? (
                loadingRows('Loading pinned')
            ) : pinnedItems.length === 0 ? (
                <Text size="sm" variant="muted" className="px-2 py-2">
                    Pinned chats show up here. To pin a chat, press and hold it, then pick Pin.
                </Text>
            ) : shownPinnedItems.length === 0 ? (
                <Text size="sm" variant="muted" className="px-2 py-2">
                    No pinned chats match your search.
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
                        searchLabel="Search chats"
                        dataAttr="today-recent-search"
                        listClassName="mt-1 flex flex-col pb-4"
                    >
                        <TodaySpacesSectionTabs
                            value={shownSection}
                            onChange={setPhoneSection}
                            counts={{ pinned: pinnedItems.length }}
                            actions={shownSection === 'recent' ? <TodayRecentFilterMenu /> : null}
                        />
                        <div className="flex flex-col gap-px" data-attr={`today-spaces-tab-panel-${shownSection}`}>
                            {shownSection === 'pinned' ? pinnedBody : recentBody}
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
                    searchLabel="Search chats"
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
                    </div>
                </TodayPaneSearchList>
                <TodaySessionBulkBar />
                <TodayListAppearanceDialog />
            </div>
        </TooltipProvider>
    )
}
