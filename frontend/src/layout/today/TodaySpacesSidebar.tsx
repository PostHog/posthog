import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronRight, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { TodayPaneRow } from './TodayPaneRow'
import { spaceLabel, todaySpacesLogic } from './todaySpacesLogic'

export function TodaySpacesSidebar(): JSX.Element {
    const {
        sortedSpaces,
        spacesLoading,
        spacesUnavailable,
        expandedSpaceIds,
        spaceTasks,
        loadingSpaceIds,
        failedSpaceIds,
        recentChats,
        conversationHistoryLoading,
    } = useValues(todaySpacesLogic)
    const { toggleSpace, loadSpaces, loadSpaceTasks } = useActions(todaySpacesLogic)
    const { location, searchParams } = useValues(router)
    const onAi = location.pathname.endsWith('/ai')

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
                <div className="TodayPane__heading Today__label">Spaces</div>
                {spacesLoading && !sortedSpaces.length ? (
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
                ) : !sortedSpaces.length ? (
                    <div className="TodayPane__state">
                        Spaces group the sessions you and your agents work on. Create one from PostHog Desktop.
                    </div>
                ) : (
                    sortedSpaces.map((space) => {
                        const expanded = expandedSpaceIds.includes(space.id)
                        const tasks = spaceTasks[space.id]
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
                    })
                )}
                <div className="TodayPane__heading Today__label">Recent chats</div>
                {conversationHistoryLoading && !recentChats.length ? (
                    <div className="TodayPane__state">
                        <Spinner />
                    </div>
                ) : !recentChats.length ? (
                    <div className="TodayPane__state">Chats with PostHog AI show up here.</div>
                ) : (
                    recentChats.map((conversation) => (
                        <TodayPaneRow
                            key={conversation.id}
                            label={conversation.title || 'Untitled chat'}
                            to={urls.ai(conversation.id)}
                            active={onAi && searchParams.chat === conversation.id}
                            dataAttr="today-recent-chat"
                        />
                    ))
                )}
            </div>
        </div>
    )
}
