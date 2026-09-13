import { Combobox } from '@base-ui/react/combobox'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useId, useMemo, useState } from 'react'

import { IconPlusSmall, IconSearch, IconX } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import { cn } from 'lib/utils/css-classes'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { AiChatListItem } from 'scenes/max/components/List/AiChatListItem'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import type { Conversation } from '~/types'

import { tasksLogic } from 'products/posthog_ai/frontend/api/logics'
import { TaskAssigneeFilterMenu, TaskListItem } from 'products/posthog_ai/frontend/api/primitives'
import type { Task } from 'products/posthog_ai/frontend/api/types'

const DATE_GROUP_ORDER = ['Today', 'Yesterday', 'Last 7 days', 'Last 30 days', 'Older'] as const

function getDateGroupLabel(dateString: string | null): string {
    if (!dateString) {
        return 'Older'
    }

    const date = new Date(dateString)
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)
    const lastWeek = new Date(today)
    lastWeek.setDate(lastWeek.getDate() - 7)
    const lastMonth = new Date(today)
    lastMonth.setDate(lastMonth.getDate() - 30)

    if (date >= today) {
        return 'Today'
    } else if (date >= yesterday) {
        return 'Yesterday'
    } else if (date >= lastWeek) {
        return 'Last 7 days'
    } else if (date >= lastMonth) {
        return 'Last 30 days'
    }
    return 'Older'
}

export type AiHistoryItem =
    | {
          kind: 'conversation'
          key: string
          title: string
          searchableText: string
          updatedAt: string | null
          conversation: Conversation
      }
    | {
          kind: 'task'
          key: string
          title: string
          searchableText: string
          updatedAt: string
          task: Task
      }

export interface AiHistoryGroup {
    value: string
    items: AiHistoryItem[]
}

export function groupAiHistory(conversationHistory: Conversation[], tasks: Task[]): AiHistoryGroup[] {
    const items: AiHistoryItem[] = []

    for (const conversation of conversationHistory) {
        if (!conversation) {
            continue
        }
        const title = conversation.title || 'Untitled conversation'
        items.push({
            kind: 'conversation',
            key: `conversation:${conversation.id}`,
            title,
            searchableText: title,
            updatedAt: conversation.updated_at,
            conversation,
        })
    }

    for (const task of tasks) {
        const title = task.title || task.slug
        items.push({
            kind: 'task',
            key: `task:${task.id}`,
            title,
            // The slug rather than `title`, which only falls back to it for untitled tasks. The server
            // also matches a task by its number, through a slug-shaped query like `TASK-42`, and the
            // run header shows that slug for people to type back. Leaving it out of this filter hides
            // a titled row the server did return.
            searchableText: `${task.title} ${task.slug} ${task.description}`,
            // A task's row is often never edited after creation, so `updated_at` would bucket a
            // task that ran an hour ago by how long ago it was created.
            updatedAt: task.last_activity_at ?? task.updated_at,
            task,
        })
    }

    items.sort((left, right) => (Date.parse(right.updatedAt ?? '') || 0) - (Date.parse(left.updatedAt ?? '') || 0))

    const grouped: Record<string, AiHistoryItem[]> = {}
    for (const item of items) {
        const label = getDateGroupLabel(item.updatedAt)
        if (!grouped[label]) {
            grouped[label] = []
        }
        grouped[label].push(item)
    }

    return DATE_GROUP_ORDER.filter((label) => grouped[label]?.length > 0).map(
        (label): AiHistoryGroup => ({ value: label, items: grouped[label] })
    )
}

export interface ConversationGroup {
    value: string
    items: Conversation[]
}

export function groupConversations(conversationHistory: Conversation[]): ConversationGroup[] {
    return groupAiHistory(conversationHistory, []).map((group) => ({
        value: group.value,
        items: group.items.flatMap((item) => (item.kind === 'conversation' ? [item.conversation] : [])),
    }))
}

function LoadTasksError({ onRetry }: { onRetry: () => void }): JSX.Element {
    return (
        <div className="mx-2 mt-2 flex items-center justify-between gap-2 rounded border border-danger bg-danger-highlight px-2 py-1.5 text-xs">
            <span>Tasks couldn't load.</span>
            <ButtonPrimitive size="xs" onClick={onRetry}>
                Retry
            </ButtonPrimitive>
        </div>
    )
}

export function NavTabChat({
    inPanel = false,
    onItemClick,
}: {
    inPanel?: boolean
    onItemClick?: () => void
}): JSX.Element {
    // The chat surface can be mounted twice at once (nav tab, kept mounted, plus the side panel),
    // so the search input's id must be per-instance to keep label/htmlFor pairing valid.
    const searchInputId = useId()
    const {
        conversationHistory,
        conversationHistoryLoading,
        currentConversationId,
        isPhaiSandboxFlagOn,
        effectivePhaiView,
    } = useValues(maxGlobalLogic)
    const {
        tasks,
        tasksLoading,
        tasksError,
        tasksNext,
        tasksLoadingMore,
        tasksSearchPending,
        searchQuery,
        taskListParams,
    } = useValues(tasksLogic)
    const { loadTasks, loadMoreTasks, setSearchQuery } = useActions(tasksLogic)
    const { location, searchParams } = useValues(router)
    const tasksEnabled = useFeatureFlag('TASKS') || isPhaiSandboxFlagOn
    const [chatSearch, setChatSearch] = useState('')
    const inputValue = tasksEnabled ? searchQuery : chatSearch
    const selectedTaskId =
        removeProjectIdIfPresent(location.pathname) === urls.ai() && typeof searchParams.task === 'string'
            ? searchParams.task
            : (location.pathname.match(/\/tasks\/([^/]+)/)?.[1] ?? null)

    const historyGroups = useMemo(
        () => groupAiHistory(conversationHistory, tasksEnabled ? tasks : []),
        [conversationHistory, tasks, tasksEnabled]
    )
    const initialLoading = historyGroups.length === 0 && (conversationHistoryLoading || (tasksEnabled && tasksLoading))
    // Typing moves the client-side filter at once, but the matching tasks are a debounce plus a round
    // trip behind it. Until they land, an empty filtered list means "still loading", not "none found".
    const taskResultsPending = tasksEnabled && (tasksSearchPending || tasksLoading)

    const setInputValue = (value: string): void => {
        if (tasksEnabled) {
            setSearchQuery(value)
        } else {
            setChatSearch(value)
        }
    }

    return (
        <div className="flex flex-col flex-1 overflow-hidden">
            <Combobox.Root
                items={historyGroups}
                itemToStringLabel={(item: AiHistoryItem) => item.searchableText}
                itemToStringValue={(item: AiHistoryItem) => item.searchableText}
                open
                autoHighlight
                inline
                inputValue={inputValue}
                onInputValueChange={setInputValue}
            >
                <div className="flex flex-col h-full min-h-0">
                    <div className={cn('flex items-center gap-1 p-2 shrink-0', inPanel && 'p-1')}>
                        <label
                            htmlFor={searchInputId}
                            className={cn(
                                'input-like flex items-center flex-1 px-1 gap-1 group h-[30px]',
                                inPanel && 'bg-fill-input'
                            )}
                        >
                            <IconSearch className="size-4 text-tertiary group-focus-within:text-primary w-4 shrink-0" />
                            <Combobox.Input
                                id={searchInputId}
                                placeholder={tasksEnabled ? 'Search all' : 'Chat history'}
                                aria-label={tasksEnabled ? 'Search chats and tasks' : 'Chat history'}
                                className="w-full text-sm bg-transparent border-none focus:outline-none focus:ring-0 transition-[width] duration-100 h-[30px]"
                                autoFocus={inPanel}
                            />
                            {inputValue && (
                                <ButtonPrimitive
                                    iconOnly
                                    onClick={() => setInputValue('')}
                                    className="shrink-0 -mr-1"
                                    tooltip="Clear search"
                                >
                                    <IconX className="size-3 text-tertiary" />
                                </ButtonPrimitive>
                            )}
                        </label>
                        {tasksEnabled && <TaskAssigneeFilterMenu />}
                        <Link
                            to={urls.ai()}
                            data-attr="nav-chat-new"
                            buttonProps={{ iconOnly: true, variant: 'outline', className: 'text-ai' }}
                            // Only the new PostHog AI view puts the task composer behind this link; every
                            // other cohort lands on the legacy chat, which can only start a conversation.
                            tooltip={effectivePhaiView === 'new' ? 'New chat or task' : 'New chat'}
                        >
                            <IconPlusSmall className="size-4" />
                        </Link>
                    </div>

                    <ScrollableShadows
                        direction="vertical"
                        className="flex flex-col flex-1 min-h-0 overflow-hidden"
                        innerClassName="flex flex-col px-1 pb-4 -mx-1 scroll-pt-8 focus-visible:outline-accent -outline-offset-2"
                        styledScrollbars
                    >
                        {initialLoading ? (
                            <div className="flex flex-col gap-1 px-1">
                                <LemonSkeleton className="h-8" />
                                <LemonSkeleton className="h-8 opacity-60" />
                                <LemonSkeleton className="h-8 opacity-30" />
                            </div>
                        ) : (
                            <>
                                <Combobox.List className="flex flex-col">
                                    {(group: AiHistoryGroup) => (
                                        <Collapsible
                                            key={`${group.value}-${!!inputValue}`}
                                            defaultOpen={
                                                !!inputValue || group.value === 'Today' || historyGroups.length === 1
                                            }
                                        >
                                            <Combobox.Group items={group.items}>
                                                <Combobox.GroupLabel
                                                    render={
                                                        <Collapsible.Trigger className="sticky top-0 bg-surface-tertiary z-4 pl-3" />
                                                    }
                                                >
                                                    {group.value}
                                                </Combobox.GroupLabel>
                                                <Collapsible.Panel className="p-1 pl-3">
                                                    <Combobox.Collection>
                                                        {(item: AiHistoryItem) =>
                                                            item.kind === 'conversation' ? (
                                                                <AiChatListItem.Root key={item.key}>
                                                                    <AiChatListItem.Group>
                                                                        <Combobox.Item
                                                                            value={item}
                                                                            render={(props) => (
                                                                                <Tooltip
                                                                                    title={item.title}
                                                                                    placement="right"
                                                                                >
                                                                                    <Link
                                                                                        {...props}
                                                                                        to={AiChatListItem.getHref(
                                                                                            item.conversation.id
                                                                                        )}
                                                                                        data-attr="nav-chat-history-conversation"
                                                                                        buttonProps={{
                                                                                            active:
                                                                                                !selectedTaskId &&
                                                                                                item.conversation.id ===
                                                                                                    currentConversationId,
                                                                                            fullWidth: true,
                                                                                            className: 'pr-0',
                                                                                            menuItem: true,
                                                                                        }}
                                                                                        onClick={(e) => {
                                                                                            e.preventDefault()
                                                                                            router.actions.push(
                                                                                                AiChatListItem.getHref(
                                                                                                    item.conversation.id
                                                                                                )
                                                                                            )
                                                                                            onItemClick?.()
                                                                                        }}
                                                                                    >
                                                                                        <AiChatListItem.Content
                                                                                            title={
                                                                                                item.conversation.title
                                                                                            }
                                                                                            status={
                                                                                                item.conversation.status
                                                                                            }
                                                                                            updatedAt={
                                                                                                item.conversation
                                                                                                    .updated_at
                                                                                            }
                                                                                        />
                                                                                    </Link>
                                                                                </Tooltip>
                                                                            )}
                                                                        />
                                                                        <AiChatListItem.Trigger />
                                                                    </AiChatListItem.Group>
                                                                    <AiChatListItem.Actions
                                                                        conversationId={item.conversation.id}
                                                                    />
                                                                </AiChatListItem.Root>
                                                            ) : (
                                                                <TaskListItem.Root key={item.key}>
                                                                    <TaskListItem.Group>
                                                                        <Combobox.Item
                                                                            value={item}
                                                                            render={(props) => (
                                                                                <Tooltip
                                                                                    title={item.title}
                                                                                    placement="right"
                                                                                >
                                                                                    <Link
                                                                                        {...props}
                                                                                        to={TaskListItem.getHref(
                                                                                            item.task.id
                                                                                        )}
                                                                                        data-attr="nav-chat-history-task"
                                                                                        buttonProps={{
                                                                                            active:
                                                                                                item.task.id ===
                                                                                                selectedTaskId,
                                                                                            fullWidth: true,
                                                                                            className: 'pr-0',
                                                                                            menuItem: true,
                                                                                        }}
                                                                                        onClick={(e) => {
                                                                                            e.preventDefault()
                                                                                            router.actions.push(
                                                                                                TaskListItem.getHref(
                                                                                                    item.task.id
                                                                                                )
                                                                                            )
                                                                                            onItemClick?.()
                                                                                        }}
                                                                                    >
                                                                                        <TaskListItem.Content
                                                                                            task={item.task}
                                                                                        />
                                                                                    </Link>
                                                                                </Tooltip>
                                                                            )}
                                                                        />
                                                                        <TaskListItem.Trigger />
                                                                    </TaskListItem.Group>
                                                                    <TaskListItem.Actions taskId={item.task.id} />
                                                                </TaskListItem.Root>
                                                            )
                                                        }
                                                    </Combobox.Collection>
                                                </Collapsible.Panel>
                                            </Combobox.Group>
                                        </Collapsible>
                                    )}
                                </Combobox.List>
                                <div className="p-2 empty:hidden">
                                    <Combobox.Empty className="empty:hidden">
                                        <div className="flex flex-col items-center justify-center text-center py-8 text-muted border border-dashed rounded-md">
                                            {taskResultsPending ? (
                                                <span className="flex items-center gap-2 text-xs">
                                                    <Spinner className="size-3" />
                                                    Loading tasks…
                                                </span>
                                            ) : (
                                                <p className="text-xs mb-0">
                                                    {tasksEnabled ? 'No chats or tasks found' : 'No chats found'}
                                                </p>
                                            )}
                                        </div>
                                    </Combobox.Empty>
                                </div>
                            </>
                        )}
                        {/* Deliberately not gated on an empty list. A failed load keeps the previous page,
                            so that gate would leave the user reading the old filter's rows with no error
                            and no retry. Nothing else reports this failure: there is no toast for it. */}
                        {tasksEnabled && tasksError && !tasksLoading && (
                            <LoadTasksError onRetry={() => loadTasks(taskListParams)} />
                        )}
                        {tasksEnabled && tasksLoading && tasks.length === 0 && historyGroups.length > 0 && (
                            <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted">
                                <Spinner className="size-3" />
                                Loading tasks…
                            </div>
                        )}
                        {tasksEnabled && tasksNext && (
                            <div className="px-2 pt-2">
                                <ButtonPrimitive
                                    fullWidth
                                    size="sm"
                                    disabled={tasksLoadingMore}
                                    onClick={() => loadMoreTasks()}
                                >
                                    {tasksLoadingMore && <Spinner className="size-3" />}
                                    {/* Wrapped so the label is not a bare text node beside the conditional
                                        spinner. A page translator swaps that node for a `<font>` element, and
                                        React then inserts the spinner against a node the DOM no longer holds. */}
                                    <span>Load more tasks</span>
                                </ButtonPrimitive>
                            </div>
                        )}
                    </ScrollableShadows>
                </div>
            </Combobox.Root>
        </div>
    )
}
