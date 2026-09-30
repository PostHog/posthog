import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Fragment } from 'react'

import { IconList, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSection, TodayPaneSectionProps } from './TodayPaneSection'
import { TodaySessionRow } from './TodaySessionRow'
import { TodayWorkSectionId, spaceLabel, todaySpacesLogic } from './todaySpacesLogic'
import { TodayWorkItem, shortTimeAgo } from './todayWorkItems'
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
            <TodayPaneRow
                key={`${item.kind}-${item.id}`}
                label={item.title || 'Untitled chat'}
                icon={<span className="TodayPane__dot" data-kind={item.kind} />}
                meta={shortTimeAgo(item.timestamp)}
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

    return (
        <div className="TodayPane">
            <button
                type="button"
                className="TodaySidebar__new"
                data-attr="today-spaces-new-chat"
                onClick={() => router.actions.push(urls.ai())}
            >
                <IconPlus />
                New chat
            </button>
            <div className="TodayPane__sections" ref={layout.measureRefs.area}>
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
                        <div className="TodayPane__state">
                            <Spinner />
                        </div>
                    ) : recentTasksUnavailable && !recentItems.length ? (
                        <div className="TodayPane__state">
                            <span>Recent sessions didn’t load.</span>
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => loadRecentTasks()}
                                data-attr="today-recent-retry"
                            >
                                Try again
                            </LemonButton>
                        </div>
                    ) : !recentItems.length ? (
                        <div className="TodayPane__state">Sessions and chats you open show up here.</div>
                    ) : (
                        <>
                            {recentTasksUnavailable && (
                                <div className="TodayPane__state">
                                    <span>Some sessions didn’t load.</span>
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        onClick={() => loadRecentTasks()}
                                        data-attr="today-recent-retry"
                                    >
                                        Try again
                                    </LemonButton>
                                </div>
                            )}
                            {recentGroups.map((group, index) => (
                                <Fragment key={group.key}>
                                    <div className={cn('TodayPane__group', index === 0 && 'TodayPane__group--first')}>
                                        {group.label}
                                    </div>
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
                        <LemonButton
                            size="xsmall"
                            icon={<IconList />}
                            active={browsingSpaces}
                            tooltip={browsingSpaces ? 'Show starred spaces only' : 'Browse all spaces'}
                            onClick={() => setBrowsingSpaces(!browsingSpaces)}
                            data-attr="today-spaces-browse"
                        />
                    }
                >
                    {spacesLoading && !visibleSpaces.length ? (
                        <div className="TodayPane__state">
                            <Spinner />
                        </div>
                    ) : spacesUnavailable ? (
                        <div className="TodayPane__state">
                            <span>Spaces didn’t load.</span>
                            <LemonButton size="small" type="secondary" onClick={() => loadSpaces()}>
                                Try again
                            </LemonButton>
                        </div>
                    ) : !visibleSpaces.length && browsingSpaces ? (
                        <div className="TodayPane__state">
                            Spaces group the sessions you and your agents work on. Create one from PostHog Desktop.
                        </div>
                    ) : (
                        <>
                            {visibleSpaces.map((space) => (
                                <TodayPaneRow
                                    key={space.id}
                                    label={spaceLabel(space)}
                                    icon={<span className="TodayPane__hash">#</span>}
                                    to={urls.taskSpace(space.id)}
                                    active={location.pathname.includes(urls.taskSpace(space.id))}
                                    dataAttr="today-space-row"
                                />
                            ))}
                            {!browsingSpaces && visibleSpaces.length <= 1 && (
                                <button
                                    type="button"
                                    className="TodayPane__add"
                                    data-attr="today-spaces-add"
                                    onClick={() => setBrowsingSpaces(true)}
                                >
                                    <IconPlus />
                                    Add the spaces you work in
                                </button>
                            )}
                        </>
                    )}
                </TodayPaneSection>
            </div>
        </div>
    )
}
