import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconList, IconPlus } from '@posthog/icons'
import { Button, Dot, Text, Toggle, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TodayPane } from './TodayPane'
import { TodayPaneGroup } from './TodayPaneGroup'
import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSection } from './TodayPaneSection'
import { TodayPaneState } from './TodayPaneState'
import { TodaySessionRow } from './TodaySessionRow'
import { spaceLabel, todaySpacesLogic } from './todaySpacesLogic'
import { TodayWorkItem, shortTimeAgo } from './todayWorkItems'

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
            />
        ) : (
            <TodayPaneRow
                key={`${item.kind}-${item.id}`}
                label={item.title || 'Untitled chat'}
                icon={<Dot />}
                meta={shortTimeAgo(item.timestamp)}
                to={urls.ai(item.id)}
                active={location.pathname.endsWith('/ai') && searchParams.chat === item.id}
                dataAttr={dataAttr}
            />
        )

    const hasPinned = pinnedItems.length > 0
    const browseLabel = browsingSpaces ? 'Show starred spaces only' : 'Browse all spaces'

    return (
        <TodayPane
            label="Spaces"
            header={
                <Button
                    variant="outline"
                    left
                    className="w-full"
                    render={<LinkPrimitive to={urls.ai()} />}
                    data-attr="today-spaces-new-chat"
                >
                    <IconPlus />
                    New chat
                </Button>
            }
        >
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
                    <TodayPaneState loading />
                ) : recentTasksUnavailable && !recentItems.length ? (
                    <TodayPaneState
                        message="Recent sessions didn’t load."
                        onRetry={() => loadRecentTasks()}
                        retrying={recentLoading}
                        retryDataAttr="today-recent-retry"
                    />
                ) : !recentItems.length ? (
                    <TodayPaneState message="Sessions and chats you open show up here." />
                ) : (
                    <>
                        {recentTasksUnavailable && (
                            <TodayPaneState
                                message="Some sessions didn’t load."
                                onRetry={() => loadRecentTasks()}
                                retrying={recentLoading}
                                retryDataAttr="today-recent-retry"
                            />
                        )}
                        {recentGroups.map((group) => (
                            <TodayPaneGroup key={group.key} label={group.label}>
                                {group.items.map((item) =>
                                    renderItem(
                                        item,
                                        item.kind === 'chat' ? 'today-recent-chat' : 'today-recent-session'
                                    )
                                )}
                            </TodayPaneGroup>
                        ))}
                    </>
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
                    <Tooltip>
                        <TooltipTrigger
                            delay={0}
                            render={
                                <Toggle
                                    size="sm"
                                    pressed={browsingSpaces}
                                    onPressedChange={setBrowsingSpaces}
                                    aria-label={browseLabel}
                                    data-attr="today-spaces-browse"
                                />
                            }
                        >
                            <IconList />
                        </TooltipTrigger>
                        <TooltipContent>{browseLabel}</TooltipContent>
                    </Tooltip>
                }
            >
                {spacesLoading && !visibleSpaces.length ? (
                    <TodayPaneState loading />
                ) : spacesUnavailable ? (
                    <TodayPaneState
                        message="Spaces didn’t load."
                        onRetry={() => loadSpaces()}
                        retrying={spacesLoading}
                        retryDataAttr="today-spaces-retry"
                    />
                ) : !visibleSpaces.length && browsingSpaces ? (
                    <TodayPaneState message="Spaces group the sessions you and your agents work on. Create one from PostHog Desktop." />
                ) : (
                    visibleSpaces.map((space) => (
                        <TodayPaneRow
                            key={space.id}
                            label={spaceLabel(space)}
                            icon={
                                <Text variant="muted" render={<span aria-hidden />} className="font-mono">
                                    #
                                </Text>
                            }
                            to={urls.taskSpace(space.id)}
                            active={location.pathname.endsWith(urls.taskSpace(space.id))}
                            dataAttr="today-space-row"
                        />
                    ))
                )}
            </TodayPaneSection>
        </TodayPane>
    )
}
