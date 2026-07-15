import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import {
    IconAI,
    IconBolt,
    IconCheckCircle,
    IconCircleDashed,
    IconGitBranch,
    IconLightBulb,
    IconPause,
    IconPlug,
    IconPlusSmall,
    IconTerminal,
    IconXCircle,
} from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonBadge } from 'lib/lemon-ui/LemonBadge'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { tasksLogic } from 'products/posthog_ai/frontend/logics/tasksLogic'
import type { Task } from 'products/posthog_ai/frontend/types/taskTypes'

import { CODE_SECTION_LABELS, CodeSceneLogicProps, CodeSceneSection, codeSceneLogic } from './codeSceneLogic'

/**
 * PostHog Code demo surface for the desktop app (products/desktop): the scenes behind the
 * "Code" navbar tab. Home shows real tasks (products/posthog_ai tasks API); the other
 * sections are demo stubs that mimic PostHog Code (github.com/posthog/code) until its
 * features are ported for real.
 */

export const scene: SceneExport<CodeSceneLogicProps> = {
    component: CodeScene,
    logic: codeSceneLogic,
    paramsToProps: ({ params: { section } }: { params: { section?: string } }) => ({
        section: (section && section in CODE_SECTION_LABELS ? section : 'home') as CodeSceneSection,
    }),
}

export function TaskStatusIcon({ task }: { task: Task }): JSX.Element {
    const status = task.latest_run?.status
    if (status === 'in_progress' || status === 'queued') {
        return <Spinner className="text-accent shrink-0" />
    }
    if (status === 'completed') {
        return <IconCheckCircle className="text-success shrink-0" />
    }
    if (status === 'failed' || status === 'cancelled') {
        return <IconXCircle className="text-danger shrink-0" />
    }
    return <IconPause className="text-muted shrink-0" />
}

function SectionHeader({
    icon,
    title,
    description,
    action,
}: {
    icon: JSX.Element
    title: string
    description: string
    action?: JSX.Element
}): JSX.Element {
    return (
        <div className="flex items-start justify-between gap-4 mb-4">
            <div className="flex items-start gap-3">
                <span className="text-2xl mt-0.5">{icon}</span>
                <div>
                    <h1 className="text-xl font-semibold mb-1">{title}</h1>
                    <p className="text-secondary text-sm mb-0 max-w-160">{description}</p>
                </div>
            </div>
            {action}
        </div>
    )
}

function CodeHome(): JSX.Element {
    const { tasks, tasksLoading } = useValues(tasksLogic)
    const { loadTasks } = useActions(tasksLogic)

    useEffect(() => {
        loadTasks({})
        // oxlint-disable-next-line exhaustive-deps
    }, [])

    const columns: LemonTableColumns<Task> = [
        {
            title: 'Task',
            key: 'title',
            render: (_, task) => (
                <div className="flex items-center gap-2">
                    <TaskStatusIcon task={task} />
                    <Link to={urls.taskDetail(task.id)} subtle className="font-medium">
                        {task.title || 'Untitled task'}
                    </Link>
                </div>
            ),
        },
        {
            title: 'Repository',
            key: 'repository',
            render: (_, task) =>
                task.repository ? (
                    <span className="flex items-center gap-1 text-secondary text-xs">
                        <IconGitBranch /> {task.repository}
                    </span>
                ) : (
                    <span className="text-muted text-xs">—</span>
                ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, task) =>
                task.latest_run ? (
                    <LemonTag
                        type={
                            task.latest_run.status === 'completed'
                                ? 'success'
                                : task.latest_run.status === 'failed' || task.latest_run.status === 'cancelled'
                                  ? 'danger'
                                  : task.latest_run.status === 'in_progress' || task.latest_run.status === 'queued'
                                    ? 'completion'
                                    : 'default'
                        }
                    >
                        {task.latest_run.status.replace('_', ' ')}
                    </LemonTag>
                ) : (
                    <LemonTag>draft</LemonTag>
                ),
        },
        {
            title: 'Updated',
            key: 'updated',
            render: (_, task) => <TZLabel time={task.updated_at} />,
        },
    ]

    return (
        <div>
            <SectionHeader
                icon={<IconTerminal />}
                title="PostHog Code"
                description="Agents that build, fix, and ship for you. Start a task and an agent will pick it up, work on a branch, and open a pull request."
                action={
                    <LemonButton type="primary" icon={<IconPlusSmall />} to={urls.taskNew()}>
                        New task
                    </LemonButton>
                }
            />
            <LemonTable
                columns={columns}
                dataSource={tasks}
                loading={tasksLoading}
                rowKey="id"
                emptyState={
                    <div className="flex flex-col items-center gap-2 py-8">
                        <span className="text-secondary">No tasks yet</span>
                        <LemonButton type="secondary" to={urls.taskNew()}>
                            Start building
                        </LemonButton>
                    </div>
                }
                onRow={(task) => ({
                    onClick: () => router.actions.push(urls.taskDetail(task.id)),
                    className: 'cursor-pointer',
                })}
            />
        </div>
    )
}

interface DemoAgent {
    name: string
    description: string
    model: string
    tools: number
}

const DEMO_AGENTS: DemoAgent[] = [
    { name: 'claude', description: 'General-purpose coding agent', model: 'claude-fable-5', tools: 18 },
    {
        name: 'code-reviewer',
        description: 'Reviews diffs for bugs and style issues',
        model: 'claude-fable-5',
        tools: 12,
    },
    { name: 'test-writer', description: 'Writes and maintains test suites', model: 'claude-sonnet-5', tools: 14 },
    {
        name: 'systematic-debugger',
        description: 'Root-causes failures methodically',
        model: 'claude-fable-5',
        tools: 16,
    },
]

function CodeAgents(): JSX.Element {
    return (
        <div>
            <SectionHeader
                icon={<IconAI />}
                title="Agents"
                description="Agent definitions available to your tasks. Each agent has its own system prompt, model, and tool access."
                action={
                    <LemonButton
                        type="primary"
                        icon={<IconPlusSmall />}
                        disabledReason="Demo: agent editing is not wired up yet"
                    >
                        New agent
                    </LemonButton>
                }
            />
            <LemonTable
                columns={[
                    {
                        title: 'Agent',
                        key: 'name',
                        render: (_, agent: DemoAgent) => <span className="font-mono font-medium">{agent.name}</span>,
                    },
                    { title: 'Description', dataIndex: 'description' },
                    {
                        title: 'Model',
                        key: 'model',
                        render: (_, agent: DemoAgent) => <LemonTag type="highlight">{agent.model}</LemonTag>,
                    },
                    { title: 'Tools', dataIndex: 'tools' },
                ]}
                dataSource={DEMO_AGENTS}
                rowKey="name"
            />
        </div>
    )
}

interface DemoSkill {
    name: string
    description: string
    source: string
}

const DEMO_SKILLS: DemoSkill[] = [
    { name: 'writing-tests', description: 'Value gate and conventions for new tests', source: 'posthog/posthog' },
    { name: 'django-migrations', description: 'Safe migration patterns for Postgres', source: 'posthog/posthog' },
    { name: 'playwright-test', description: 'Author non-flaky browser tests', source: 'posthog/posthog' },
    { name: 'deep-research', description: 'Multi-source fact-checked research reports', source: 'built-in' },
    { name: 'dataviz', description: 'Design-system-aware charts and dashboards', source: 'built-in' },
]

function CodeSkills(): JSX.Element {
    return (
        <div>
            <SectionHeader
                icon={<IconLightBulb />}
                title="Skills"
                description="Reusable instructions agents load on demand: workflows, conventions, and domain knowledge."
                action={
                    <LemonButton
                        type="primary"
                        icon={<IconPlusSmall />}
                        disabledReason="Demo: skill editing is not wired up yet"
                    >
                        New skill
                    </LemonButton>
                }
            />
            <LemonTable
                columns={[
                    {
                        title: 'Skill',
                        key: 'name',
                        render: (_, skill: DemoSkill) => <span className="font-mono font-medium">/{skill.name}</span>,
                    },
                    { title: 'Description', dataIndex: 'description' },
                    {
                        title: 'Source',
                        key: 'source',
                        render: (_, skill: DemoSkill) => <LemonTag>{skill.source}</LemonTag>,
                    },
                ]}
                dataSource={DEMO_SKILLS}
                rowKey="name"
            />
        </div>
    )
}

interface DemoMcpServer {
    name: string
    transport: string
    tools: number
    status: 'connected' | 'disconnected'
}

const DEMO_MCP_SERVERS: DemoMcpServer[] = [
    { name: 'posthog', transport: 'streamable-http', tools: 42, status: 'connected' },
    { name: 'github', transport: 'streamable-http', tools: 26, status: 'connected' },
    { name: 'grafana', transport: 'stdio', tools: 15, status: 'disconnected' },
]

function CodeMcpServers(): JSX.Element {
    return (
        <div>
            <SectionHeader
                icon={<IconPlug />}
                title="MCP servers"
                description="Model Context Protocol servers your agents can call: extra tools, data sources, and integrations."
                action={
                    <LemonButton
                        type="primary"
                        icon={<IconPlusSmall />}
                        disabledReason="Demo: MCP configuration is not wired up yet"
                    >
                        Add server
                    </LemonButton>
                }
            />
            <LemonTable
                columns={[
                    {
                        title: 'Server',
                        key: 'name',
                        render: (_, server: DemoMcpServer) => (
                            <span className="font-mono font-medium">{server.name}</span>
                        ),
                    },
                    { title: 'Transport', dataIndex: 'transport' },
                    { title: 'Tools', dataIndex: 'tools' },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, server: DemoMcpServer) => (
                            <LemonTag type={server.status === 'connected' ? 'success' : 'danger'}>
                                {server.status}
                            </LemonTag>
                        ),
                    },
                ]}
                dataSource={DEMO_MCP_SERVERS}
                rowKey="name"
            />
        </div>
    )
}

function CodeCommandCenter(): JSX.Element {
    const { tasks } = useValues(tasksLogic)
    const running = tasks.filter(
        (task: Task) => task.latest_run?.status === 'in_progress' || task.latest_run?.status === 'queued'
    )

    return (
        <div>
            <SectionHeader
                icon={<IconBolt />}
                title="Command Center"
                description="Everything running right now: live agent runs, queued tasks, and long-running commands."
            />
            {running.length === 0 ? (
                <div className="border border-dashed border-primary rounded p-8 flex flex-col items-center gap-2">
                    <IconBolt className="text-2xl text-muted" />
                    <span className="text-secondary">Nothing running right now</span>
                    <span className="text-muted text-xs">Active agent runs will show up here as they start.</span>
                </div>
            ) : (
                <div className="flex flex-col gap-2">
                    {running.map((task: Task) => (
                        <Link
                            key={task.id}
                            to={urls.taskDetail(task.id)}
                            className="border border-primary rounded p-3 flex items-center gap-3 hover:bg-fill-highlight-50"
                            subtle
                        >
                            <Spinner className="text-accent" />
                            <span className="font-medium flex-1 truncate">{task.title || 'Untitled task'}</span>
                            {task.latest_run?.branch && (
                                <span className="flex items-center gap-1 text-xs text-secondary">
                                    <IconGitBranch /> {task.latest_run.branch}
                                </span>
                            )}
                            <LemonBadge.Number count={1} status="primary" size="small" />
                        </Link>
                    ))}
                </div>
            )}
        </div>
    )
}

interface DemoContext {
    name: string
    description: string
    items: number
}

const DEMO_CONTEXTS: DemoContext[] = [
    { name: 'posthog/posthog', description: 'Main repository context: layout, conventions, hot paths', items: 128 },
    { name: 'support-rotation', description: 'Zendesk tickets and recent incident threads', items: 34 },
    { name: 'growth-experiments', description: 'Active experiments and their result docs', items: 12 },
]

function CodeContexts(): JSX.Element {
    return (
        <div>
            <SectionHeader
                icon={<IconCircleDashed />}
                title="Contexts"
                description="Curated channels of knowledge agents pull into their runs: repos, docs, tickets, and conversations."
                action={
                    <LemonButton
                        type="primary"
                        icon={<IconPlusSmall />}
                        disabledReason="Demo: context editing is not wired up yet"
                    >
                        New context
                    </LemonButton>
                }
            />
            <LemonTable
                columns={[
                    {
                        title: 'Context',
                        key: 'name',
                        render: (_, context: DemoContext) => <span className="font-medium">{context.name}</span>,
                    },
                    { title: 'Description', dataIndex: 'description' },
                    { title: 'Items', dataIndex: 'items' },
                ]}
                dataSource={DEMO_CONTEXTS}
                rowKey="name"
            />
        </div>
    )
}

const SECTION_COMPONENTS: Record<CodeSceneSection, () => JSX.Element> = {
    home: CodeHome,
    agents: CodeAgents,
    skills: CodeSkills,
    'mcp-servers': CodeMcpServers,
    'command-center': CodeCommandCenter,
    contexts: CodeContexts,
}

export function CodeScene(): JSX.Element {
    const { section } = useValues(codeSceneLogic)
    const SectionComponent = SECTION_COMPONENTS[section] ?? CodeHome
    return (
        <div className="max-w-240 mx-auto w-full">
            <SectionComponent />
        </div>
    )
}

export default CodeScene
