import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Fragment } from 'react'

import { IconChevronRight, IconList, IconPlus, IconStar, IconStarFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSection } from './TodayPaneSection'
import { spaceLabel, todaySpacesLogic } from './todaySpacesLogic'
import { TodayWorkItem, shortTimeAgo } from './todayWorkItems'

export function TodaySpacesSidebar(): JSX.Element {
    const {
        visibleSpaces,
        browsingSpaces,
        spacesLoading,
        spacesUnavailable,
        expandedSpaceIds,
        spaceTasks,
        loadingSpaceIds,
        failedSpaceIds,
        pinnedItems,
        recentItems,
        recentGroups,
        recentLoading,
        recentTasksUnavailable,
        collapsedSections,
    } = useValues(todaySpacesLogic)
    const {
        toggleSpace,
        loadSpaces,
        loadSpaceTasks,
        loadRecentTasks,
        toggleSection,
        setBrowsingSpaces,
        setSpaceStarred,
    } = useActions(todaySpacesLogic)
    const { location, searchParams } = useValues(router)
    const onAi = location.pathname.endsWith('/ai')

    const renderItem = (item: TodayWorkItem, dataAttr: string): JSX.Element => (
        <TodayPaneRow
            key={`${item.kind}-${item.id}`}
            label={item.title || (item.kind === 'chat' ? 'Untitled chat' : 'Untitled session')}
            icon={<span className="TodayPane__dot" data-kind={item.kind} data-status={item.status ?? undefined} />}
            meta={shortTimeAgo(item.timestamp)}
            to={item.kind === 'chat' ? urls.ai(item.id) : urls.aiTask(item.id)}
            active={onAi && (item.kind === 'chat' ? searchParams.chat : searchParams.task) === item.id}
            dataAttr={dataAttr}
        />
    )

    const hasPinned = pinnedItems.length > 0

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
            <div className="TodayPane__scroll">
                {hasPinned && (
                    <TodayPaneSection
                        label="Pinned"
                        open={!collapsedSections.includes('pinned')}
                        count={pinnedItems.length}
                        onToggle={() => toggleSection('pinned')}
                        dataAttr="today-section-pinned"
                    >
                        {pinnedItems.map((item) => renderItem(item, 'today-pinned-session'))}
                    </TodayPaneSection>
                )}
                <TodayPaneSection
                    label="Recent"
                    open={!collapsedSections.includes('recent')}
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
                        recentGroups.map((group, index) => (
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
                        ))
                    )}
                </TodayPaneSection>
                <TodayPaneSection
                    label="Spaces"
                    open={!collapsedSections.includes('spaces')}
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
                            {visibleSpaces.map((space) => {
                                const expanded = expandedSpaceIds.includes(space.id)
                                const tasks = spaceTasks[space.id]
                                const personal = space.system_role === 'personal'
                                return (
                                    <div key={space.id}>
                                        <TodayPaneRow
                                            label={spaceLabel(space)}
                                            icon={<span className="TodayPane__hash">#</span>}
                                            dataAttr="today-space-row"
                                            onClick={() => toggleSpace(space.id)}
                                            trailing={
                                                <IconChevronRight
                                                    className={cn('TodayPaneRow__chevron', expanded && 'rotate-90')}
                                                />
                                            }
                                            action={
                                                personal ? null : (
                                                    <LemonButton
                                                        size="xsmall"
                                                        icon={space.starred ? <IconStarFilled /> : <IconStar />}
                                                        tooltip={space.starred ? 'Unstar space' : 'Star space'}
                                                        onClick={() => setSpaceStarred(space.id, !space.starred)}
                                                        data-attr="today-space-star"
                                                    />
                                                )
                                            }
                                        />
                                        {expanded &&
                                            (tasks === undefined ? (
                                                loadingSpaceIds.includes(space.id) ? (
                                                    <div className="TodayPane__state TodayPane__state--nested">
                                                        <Spinner />
                                                    </div>
                                                ) : failedSpaceIds.includes(space.id) ? (
                                                    <div className="TodayPane__state TodayPane__state--nested">
                                                        <span>Couldn’t load this space’s sessions.</span>
                                                        <LemonButton
                                                            size="xsmall"
                                                            type="secondary"
                                                            onClick={() => loadSpaceTasks(space.id)}
                                                            data-attr="today-space-tasks-retry"
                                                        >
                                                            Try again
                                                        </LemonButton>
                                                    </div>
                                                ) : null
                                            ) : tasks.length === 0 ? (
                                                <div className="TodayPane__state TodayPane__state--nested">
                                                    No sessions yet.
                                                </div>
                                            ) : (
                                                tasks.map((task) => (
                                                    <TodayPaneRow
                                                        key={task.id}
                                                        depth={1}
                                                        label={task.title || 'Untitled session'}
                                                        to={urls.aiTask(task.id)}
                                                        active={onAi && searchParams.task === task.id}
                                                        dataAttr="today-space-task"
                                                    />
                                                ))
                                            ))}
                                    </div>
                                )
                            })}
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
