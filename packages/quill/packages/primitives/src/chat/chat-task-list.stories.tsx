import type { Meta, StoryObj } from '@storybook/react'
import * as React from 'react'

import { Button } from '../button'
import {
    ChatTask,
    ChatTaskDetail,
    ChatTaskList,
    ChatTaskListContent,
    ChatTaskListCount,
    ChatTaskListLabel,
    ChatTaskListProgress,
    ChatTaskListTrigger,
    type ChatTaskStatus,
} from './chat-task-list'

const meta: Meta<typeof ChatTaskList> = {
    title: 'Primitives/Chat/ChatTaskList',
    component: ChatTaskList,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

const TODOS = [
    'Scaffold the project structure, Scaffold the project structure and some more for longer text',
    'Build the component registry',
    'Implement entitlement gating',
    'Wire up Stripe checkout',
    'Polish the landing page',
]

const STEP_MS = 1600

function statusesFor(current: number, total: number): ChatTaskStatus[] {
    return Array.from({ length: total }, (_, index) => {
        if (index < current) {
            return 'done'
        }
        return index === current ? 'active' : 'pending'
    })
}

function TodoList({ current }: { current: number }): React.ReactElement {
    const statuses = statusesFor(current, TODOS.length)
    return (
        <ChatTaskList value={Math.max(current, 0)} total={TODOS.length} defaultOpen>
            <ChatTaskListTrigger>
                <ChatTaskListProgress />
                <ChatTaskListLabel>To-dos</ChatTaskListLabel>
                <ChatTaskListCount />
            </ChatTaskListTrigger>
            <ChatTaskListContent>
                {TODOS.map((label, index) => (
                    <ChatTask key={label} status={statuses[index]}  className="whitespace-normal">
                        {label}
                    </ChatTask>
                ))}
            </ChatTaskListContent>
        </ChatTaskList>
    )
}

/** Mid-plan: two done, one running, the rest waiting. The header ring tracks the same count. */
export const Running: Story = {
    render: () => (
        <div className="w-[420px]">
            <TodoList current={2} />
        </div>
    ),
}

/** Nothing started yet — the header shows a plain list, not an empty ring. */
export const NotStarted: Story = {
    render: () => (
        <div className="w-[420px]">
            <TodoList current={-1} />
        </div>
    ),
}

/** Every step landed: the header turns over to a check and the count reads full. */
export const Complete: Story = {
    render: () => (
        <div className="w-[420px]">
            <TodoList current={TODOS.length} />
        </div>
    ),
}

/** Collapsed — the resting state once the plan is just history in a long transcript. */
export const Collapsed: Story = {
    render: () => (
        <div className="w-[420px]">
            <ChatTaskList value={5} total={5}>
                <ChatTaskListTrigger>
                    <ChatTaskListProgress />
                    <ChatTaskListLabel>To-dos</ChatTaskListLabel>
                    <ChatTaskListCount />
                </ChatTaskListTrigger>
                <ChatTaskListContent>
                    {TODOS.map((label) => (
                        <ChatTask key={label} status="done">
                            {label}
                        </ChatTask>
                    ))}
                </ChatTaskListContent>
            </ChatTaskList>
        </div>
    ),
}

/** The four task states together, so the bullets and inks can be compared at rest. */
export const TaskStates: Story = {
    render: () => (
        <div className="w-[420px]">
            <ChatTaskList value={1} total={4} defaultOpen>
                <ChatTaskListTrigger>
                    <ChatTaskListProgress />
                    <ChatTaskListLabel>States</ChatTaskListLabel>
                    <ChatTaskListCount />
                </ChatTaskListTrigger>
                <ChatTaskListContent>
                    <ChatTask status="done">Done — settled, and it worked</ChatTask>
                    <ChatTask status="active">Active — running right now</ChatTask>
                    <ChatTask status="pending">Pending — not started</ChatTask>
                    <ChatTask status="failed">
                        Failed — it broke
                        <ChatTaskDetail>exit 1</ChatTaskDetail>
                    </ChatTask>
                </ChatTaskListContent>
            </ChatTaskList>
        </div>
    ),
}

const LONG = 'Pin the algorithm to HS256 and validate the issuer and audience claims on every incoming request'

/**
 * A step that outgrows its row wraps, and its bullet stays on the first line rather than floating
 * into the middle of the paragraph. Pass `truncate` to clamp it to one line instead — the label and
 * its detail clip together, so the ellipsis lands wherever the room runs out.
 */
export const LongLabels: Story = {
    render: () => (
        <div className="w-[320px]">
            <ChatTaskList value={1} total={3} defaultOpen>
                <ChatTaskListTrigger>
                    <ChatTaskListProgress />
                    <ChatTaskListLabel>Wrapping vs truncating</ChatTaskListLabel>
                    <ChatTaskListCount />
                </ChatTaskListTrigger>
                <ChatTaskListContent>
                    <ChatTask status="done">{LONG}</ChatTask>
                    <ChatTask status="active" truncate>
                        {LONG}
                    </ChatTask>
                    <ChatTask status="failed">
                        {LONG}
                        <ChatTaskDetail>exit 1: port 8000 already in use</ChatTaskDetail>
                    </ChatTask>
                </ChatTaskListContent>
            </ChatTaskList>
        </div>
    ),
}

/**
 * Setting up a sandbox is the same primitive — a plan, worked through. Nothing here is a `variant`:
 * it's the sandbox's own copy, plus `ChatTaskDetail` carrying what each step produced and a `failed`
 * step showing why the environment never came up.
 */
export const SandboxSetup: Story = {
    render: () => (
        <div className="w-[420px]">
            <ChatTaskList value={2} total={5} defaultOpen>
                <ChatTaskListTrigger>
                    <ChatTaskListProgress />
                    <ChatTaskListLabel>Setting up sandbox</ChatTaskListLabel>
                    <ChatTaskListCount />
                </ChatTaskListTrigger>
                <ChatTaskListContent>
                    <ChatTask status="done">
                        Pull image
                        <ChatTaskDetail>node:22 · 1.2s</ChatTaskDetail>
                    </ChatTask>
                    <ChatTask status="done">
                        Clone repository
                        <ChatTaskDetail>3.4s</ChatTaskDetail>
                    </ChatTask>
                    <ChatTask status="failed">
                        Start services
                        <ChatTaskDetail>exit 1: port 8000 already in use</ChatTaskDetail>
                    </ChatTask>
                    <ChatTask status="pending">Install dependencies</ChatTask>
                    <ChatTask status="pending">Run migrations</ChatTask>
                </ChatTaskListContent>
            </ChatTaskList>
        </div>
    ),
}

/** A sandbox that came up clean, for comparison against the failure above. */
export const SandboxReady: Story = {
    render: () => (
        <div className="w-[420px]">
            <ChatTaskList value={3} total={3}>
                <ChatTaskListTrigger>
                    <ChatTaskListProgress />
                    <ChatTaskListLabel>Sandbox ready</ChatTaskListLabel>
                    <ChatTaskListCount />
                </ChatTaskListTrigger>
                <ChatTaskListContent>
                    <ChatTask status="done">
                        Pull image
                        <ChatTaskDetail>node:22 · 1.2s</ChatTaskDetail>
                    </ChatTask>
                    <ChatTask status="done">
                        Install dependencies
                        <ChatTaskDetail>18.9s</ChatTaskDetail>
                    </ChatTask>
                    <ChatTask status="done">
                        Start services
                        <ChatTaskDetail>web on :8000</ChatTaskDetail>
                    </ChatTask>
                </ChatTaskListContent>
            </ChatTaskList>
        </div>
    ),
}

function LiveTaskList(): React.ReactElement {
    const [runId, setRunId] = React.useState(0)
    const [current, setCurrent] = React.useState(-1)

    React.useEffect(() => {
        setCurrent(-1)
        const timers = [setTimeout(() => setCurrent(0), 700)]
        for (let index = 0; index < TODOS.length; index++) {
            timers.push(setTimeout(() => setCurrent(index + 1), 700 + (index + 1) * STEP_MS))
        }
        return () => timers.forEach(clearTimeout)
    }, [runId])

    return (
        <div className="flex w-[420px] flex-col gap-4">
            <TodoList current={current} />
            <Button variant="outline" size="sm" className="self-start" onClick={() => setRunId((id) => id + 1)}>
                Replay
            </Button>
        </div>
    )
}

/**
 * The whole arc: list icon → filling ring → check, with the count rolling a digit at a time as each
 * step lands. The app owns the timing; the primitive owns the roll and the ring.
 */
export const Live: Story = {
    render: () => <LiveTaskList />,
}
