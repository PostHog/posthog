import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import {
    IconAI,
    IconBolt,
    IconCheckCircle,
    IconCircleDashed,
    IconGitBranch,
    IconHome,
    IconLetter,
    IconLightBulb,
    IconPause,
    IconPlug,
    IconPlusSmall,
    IconXCircle,
} from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { dayjs } from 'lib/dayjs'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Label } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { tasksLogic } from 'products/posthog_ai/frontend/logics/tasksLogic'
import type { Task } from 'products/posthog_ai/frontend/types/taskTypes'

/**
 * The "Code" navbar tab (desktop app demo): a sidepanel that mimics the PostHog Code
 * (github.com/posthog/code) sidebar — nav items on top, the task list below. Inbox and
 * tasks link to the real PostHog surfaces; the other sections open demo stubs in
 * scenes/code/CodeScene.
 */

function formatRelativeShort(timestamp: string): string {
    const diffMinutes = dayjs().diff(dayjs(timestamp), 'minute')
    if (diffMinutes < 1) {
        return 'now'
    }
    if (diffMinutes < 60) {
        return `${diffMinutes}m`
    }
    const diffHours = Math.floor(diffMinutes / 60)
    if (diffHours < 24) {
        return `${diffHours}h`
    }
    const diffDays = Math.floor(diffHours / 24)
    if (diffDays < 30) {
        return `${diffDays}d`
    }
    return `${Math.floor(diffDays / 30)}mo`
}

function TaskStatusIcon({ task }: { task: Task }): JSX.Element {
    const status = task.latest_run?.status
    if (status === 'in_progress' || status === 'queued') {
        return <Spinner className="text-accent size-3 shrink-0" />
    }
    if (status === 'completed') {
        return <IconCheckCircle className="text-success size-3 shrink-0" />
    }
    if (status === 'failed' || status === 'cancelled') {
        return <IconXCircle className="text-danger size-3 shrink-0" />
    }
    return <IconPause className="text-tertiary size-3 shrink-0" />
}

function CodeNavRow({
    icon,
    label,
    active,
    to,
    endContent,
}: {
    icon: JSX.Element
    label: string
    active?: boolean
    to: string
    endContent?: JSX.Element
}): JSX.Element {
    // A real link, so the desktop link context menu (open in new tab/window, copy URL, ...)
    // and cmd/ctrl+click apply to these rows like everywhere else
    return (
        <Link
            to={to}
            buttonProps={{
                menuItem: true,
                active,
                className: 'w-full text-[13px] leading-snug',
            }}
            data-attr={`nav-code-${label.toLowerCase().replace(/\s+/g, '-')}`}
        >
            <span className={cn('flex size-4 shrink-0 items-center opacity-80', active && 'opacity-100')}>{icon}</span>
            <span className="flex-1 truncate text-left">{label}</span>
            {endContent}
        </Link>
    )
}

export function NavTabCode(): JSX.Element {
    const { tasks, tasksLoading, taskListParams } = useValues(tasksLogic)
    const { loadTasks } = useActions(tasksLogic)
    const { location } = useValues(router)
    // Demo-only: mimics PostHog Code's channels/contexts feature toggle
    const [contextsEnabled, setContextsEnabled] = useState(false)

    useEffect(() => {
        // Same filtered params the tasks scene uses (own tasks by default) — an unfiltered
        // load also returns internal scout runs whose titles are raw prompts
        loadTasks(taskListParams)
        // oxlint-disable-next-line exhaustive-deps
    }, [])

    const currentPath = removeProjectIdIfPresent(location.pathname)
    const isCodeSection = (section?: string): boolean =>
        currentPath === (section ? `/code/${section}` : '/code') || (!section && currentPath === '/code/home')

    const runningCount = tasks.filter(
        (task: Task) => task.latest_run?.status === 'in_progress' || task.latest_run?.status === 'queued'
    ).length

    return (
        <div className="flex flex-col h-full min-h-0">
            {/* Nav section, mirroring PostHog Code's SidebarNavSection */}
            <div className="flex flex-col shrink-0 gap-px px-2 py-2">
                <div className="mb-2">
                    <CodeNavRow
                        icon={<IconPlusSmall />}
                        label="New task"
                        active={currentPath === '/tasks/new'}
                        to={urls.taskNew()}
                    />
                </div>
                <CodeNavRow icon={<IconHome />} label="Home" active={isCodeSection()} to={urls.code()} />
                <CodeNavRow
                    icon={<IconLetter />}
                    label="Inbox"
                    active={currentPath.startsWith('/inbox')}
                    to={urls.inbox()}
                    endContent={
                        <LemonTag type="warning" size="small">
                            Beta
                        </LemonTag>
                    }
                />
                <CodeNavRow
                    icon={<IconAI />}
                    label="Agents"
                    active={isCodeSection('agents')}
                    to={urls.code('agents')}
                />
                <CodeNavRow
                    icon={<IconLightBulb />}
                    label="Skills"
                    active={isCodeSection('skills')}
                    to={urls.code('skills')}
                />
                <CodeNavRow
                    icon={<IconPlug />}
                    label="MCP servers"
                    active={isCodeSection('mcp-servers')}
                    to={urls.code('mcp-servers')}
                />
                <CodeNavRow
                    icon={<IconBolt />}
                    label="Command Center"
                    active={isCodeSection('command-center')}
                    to={urls.code('command-center')}
                    endContent={
                        runningCount > 0 ? (
                            <span className="shrink-0 rounded bg-fill-highlight-100 px-1 text-[11px] text-secondary">
                                {runningCount > 99 ? '99+' : runningCount}
                            </span>
                        ) : undefined
                    }
                />
                <div className="flex w-full items-center gap-1.5 px-2 py-1 text-[13px] leading-snug">
                    <span className="flex size-4 shrink-0 items-center opacity-80">
                        <IconCircleDashed />
                    </span>
                    <Link
                        to={urls.code('contexts')}
                        subtle
                        className="flex-1 truncate text-left"
                        data-attr="nav-code-contexts"
                    >
                        Contexts
                    </Link>
                    <LemonTag type="completion" size="small">
                        Alpha
                    </LemonTag>
                    <LemonSwitch checked={contextsEnabled} onChange={setContextsEnabled} size="xsmall" />
                </div>
            </div>

            {/* Task list, mirroring PostHog Code's SidebarMenu/TaskListView */}
            <div className="flex items-center justify-between px-3 pt-1">
                <Label intent="menu" className="text-xxs text-secondary">
                    Tasks
                </Label>
            </div>
            <ScrollableShadows direction="vertical" className="flex-1 min-h-0" innerClassName="px-2 pb-2">
                <div className="flex flex-col gap-px">
                    {tasksLoading && tasks.length === 0 ? (
                        <div className="flex items-center gap-2 px-2 py-1.5 text-[13px] text-secondary">
                            <Spinner className="size-3" /> Loading tasks...
                        </div>
                    ) : tasks.length === 0 ? (
                        <div className="flex flex-col items-center gap-2 px-2 py-6">
                            <span className="text-[13px] text-secondary">No tasks yet</span>
                            <Link
                                to={urls.taskNew()}
                                buttonProps={{ className: 'rounded-md bg-fill-highlight-100 px-3 py-1.5 text-[13px]' }}
                                data-attr="nav-code-start-building"
                            >
                                Start building
                            </Link>
                        </div>
                    ) : (
                        tasks.map((task: Task) => (
                            <Link
                                key={task.id}
                                to={urls.taskDetail(task.id)}
                                buttonProps={{
                                    menuItem: true,
                                    active: currentPath === `/tasks/${task.id}`,
                                    className: 'group w-full text-[13px] leading-snug',
                                }}
                                data-attr="nav-code-task"
                            >
                                <TaskStatusIcon task={task} />
                                <span className="flex-1 truncate text-left">{task.title || 'Untitled task'}</span>
                                {task.latest_run?.branch ? (
                                    <span className="flex h-4 max-w-24 shrink-0 items-center gap-0.5 rounded bg-fill-highlight-100 px-1 text-[11px] text-secondary">
                                        <IconGitBranch className="size-2.5 shrink-0" />
                                        <span className="truncate">{task.latest_run.branch}</span>
                                    </span>
                                ) : (
                                    <span className="shrink-0 text-[11px] text-tertiary">
                                        {formatRelativeShort(task.updated_at)}
                                    </span>
                                )}
                            </Link>
                        ))
                    )}
                </div>
            </ScrollableShadows>
        </div>
    )
}
