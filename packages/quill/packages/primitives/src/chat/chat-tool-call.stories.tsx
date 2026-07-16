import type { Meta, StoryObj } from '@storybook/react'
import { FileIcon, PencilIcon, SearchIcon, TerminalIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from '../button'
import { ChatMarker, ChatMarkerContent, ChatMarkerIcon } from './chat-marker'
import { ChatSource, ChatSourceList, ChatSourceTitle, ChatSourceUrl, type ChatSourceStatus } from './chat-source'
import { ChatToolCall, ChatToolCallContent, ChatToolCallLabel, ChatToolCallTrigger, ChatToolCallValue } from './chat-tool-call'

const meta: Meta<typeof ChatToolCall> = {
    title: 'Primitives/Chat/ChatToolCall',
    component: ChatToolCall,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

const QUERY = 'JWT auth vulnerabilities and middleware security best practices'

const SITES = [
    { title: 'JWT verification best practices', url: 'auth0.com/blog/jwt-security-best-practices' },
    { title: 'Node.js authentication security guide', url: 'owasp.org/www-project-nodejs-goat' },
    { title: 'JWT attacks · Web Security Academy', url: 'portswigger.net/web-security/jwt' },
]

const TIMELINE = [
    { discover: 600, finish: 2400 },
    { discover: 1600, finish: 4000 },
    { discover: 2800, finish: 5600 },
]

/**
 * The default shape: the row is the joined-up summary of what happened, and the calls behind it are
 * one `ChatMarker` each — icon + text is exactly what a marker is. The summary carries no icon,
 * because no single icon is honest about three different tools.
 */
export const Grouped: Story = {
    render: () => (
        <div className="w-[460px]">
            <ChatToolCall status="done" defaultOpen>
                <ChatToolCallTrigger>
                    <ChatToolCallLabel>Read 2 files · Edited 1 file · Ran 1 command</ChatToolCallLabel>
                </ChatToolCallTrigger>
                <ChatToolCallContent>
                    <ChatMarker>
                        <ChatMarkerIcon>
                            <FileIcon />
                        </ChatMarkerIcon>
                        <ChatMarkerContent>Read auth/middleware.ts</ChatMarkerContent>
                    </ChatMarker>
                    <ChatMarker>
                        <ChatMarkerIcon>
                            <FileIcon />
                        </ChatMarkerIcon>
                        <ChatMarkerContent>Read auth/verify.test.ts</ChatMarkerContent>
                    </ChatMarker>
                    <ChatMarker>
                        <ChatMarkerIcon>
                            <PencilIcon />
                        </ChatMarkerIcon>
                        <ChatMarkerContent>Edited auth/middleware.ts</ChatMarkerContent>
                    </ChatMarker>
                    <ChatMarker>
                        <ChatMarkerIcon>
                            <TerminalIcon />
                        </ChatMarkerIcon>
                        <ChatMarkerContent>pnpm test — 12 passed</ChatMarkerContent>
                    </ChatMarker>
                </ChatToolCallContent>
            </ChatToolCall>
        </div>
    ),
}

/** Collapsed — the resting state in a transcript. The chevron only appears once you reach for it. */
export const Collapsed: Story = {
    render: () => (
        <div className="w-[460px]">
            <ChatToolCall status="done">
                <ChatToolCallTrigger>
                    <ChatToolCallLabel>Read 2 files · Edited 1 file · Ran 1 command</ChatToolCallLabel>
                </ChatToolCallTrigger>
                <ChatToolCallContent>
                    <ChatMarker>
                        <ChatMarkerIcon>
                            <FileIcon />
                        </ChatMarkerIcon>
                        <ChatMarkerContent>Read auth/middleware.ts</ChatMarkerContent>
                    </ChatMarker>
                </ChatToolCallContent>
            </ChatToolCall>
        </div>
    ),
}

function WebSearch({ statuses, running }: { statuses: ChatSourceStatus[]; running: boolean }): React.ReactElement {
    return (
        <ChatToolCall status={running ? 'running' : 'done'} defaultOpen>
            <ChatToolCallTrigger>
                <ChatToolCallLabel>
                    {running ? 'Searching' : `Searched ${SITES.length} sources`}
                    <ChatToolCallValue>{QUERY}</ChatToolCallValue>
                </ChatToolCallLabel>
            </ChatToolCallTrigger>
            <ChatToolCallContent>
                <ChatSourceList>
                    {SITES.map((site, index) => (
                        <ChatSource key={site.url} status={statuses[index]} href={`https://${site.url}`}>
                            <ChatSourceTitle>{site.title}</ChatSourceTitle>
                            <ChatSourceUrl>{site.url}</ChatSourceUrl>
                        </ChatSource>
                    ))}
                </ChatSourceList>
            </ChatToolCallContent>
        </ChatToolCall>
    )
}

/** One tool that returned pages: the rows are sources, which bring their own fetch bullets. */
export const WebSearchSources: Story = {
    render: () => (
        <div className="w-[460px]">
            <WebSearch statuses={['pending', 'loading', 'done']} running />
        </div>
    ),
}

/** Settled: the verb goes quiet, the query it searched for reads as the fact worth keeping. */
export const Done: Story = {
    render: () => (
        <div className="w-[460px]">
            <WebSearch statuses={['done', 'done', 'done']} running={false} />
        </div>
    ),
}

/**
 * The call came back wrong: the shimmer stops and the row goes destructive, but whatever it did
 * return stays readable — a failing tool's partial output is usually the whole story.
 */
export const Error: Story = {
    render: () => (
        <div className="w-[460px]">
            <ChatToolCall status="error" defaultOpen>
                <ChatToolCallTrigger>
                    <ChatToolCallLabel>
                        Couldn’t search
                        <ChatToolCallValue>{QUERY}</ChatToolCallValue>
                    </ChatToolCallLabel>
                </ChatToolCallTrigger>
                <ChatToolCallContent>
                    <ChatSourceList>
                        <ChatSource status="done" href={`https://${SITES[0].url}`}>
                            <ChatSourceTitle>{SITES[0].title}</ChatSourceTitle>
                            <ChatSourceUrl>{SITES[0].url}</ChatSourceUrl>
                        </ChatSource>
                        <ChatSource status="pending">
                            <ChatSourceTitle>Rate limited after 1 result</ChatSourceTitle>
                            <ChatSourceUrl>retry in 30s</ChatSourceUrl>
                        </ChatSource>
                    </ChatSourceList>
                </ChatToolCallContent>
            </ChatToolCall>
        </div>
    ),
}

/** Not every tool returns rows — the content slot takes whatever the call produced. */
export const RawOutput: Story = {
    render: () => (
        <div className="w-[460px]">
            <ChatToolCall status="done" defaultOpen>
                <ChatToolCallTrigger>
                    <ChatToolCallLabel>
                        Ran
                        <ChatToolCallValue>pnpm build</ChatToolCallValue>
                    </ChatToolCallLabel>
                </ChatToolCallTrigger>
                <ChatToolCallContent>
                    <pre className="text-muted-foreground overflow-x-auto text-xs">
                        {'✓ 114 modules transformed\n✓ built in 1.51s'}
                    </pre>
                </ChatToolCallContent>
            </ChatToolCall>
        </div>
    ),
}

/** A source row without an href is static text — no hover fill, no out-arrow. */
export const SourcesWithoutLinks: Story = {
    render: () => (
        <div className="w-[460px]">
            <ChatToolCall status="done" defaultOpen>
                <ChatToolCallTrigger>
                    <ChatToolCallLabel>
                        Searched the knowledge base
                        <ChatToolCallValue>onboarding</ChatToolCallValue>
                    </ChatToolCallLabel>
                </ChatToolCallTrigger>
                <ChatToolCallContent>
                    <ChatSourceList>
                        <ChatSource status="done">
                            <ChatSourceTitle>Internal runbook</ChatSourceTitle>
                            <ChatSourceUrl>indexed 2 days ago</ChatSourceUrl>
                        </ChatSource>
                    </ChatSourceList>
                </ChatToolCallContent>
            </ChatToolCall>
        </div>
    ),
}

function LiveSearch(): React.ReactElement {
    const [runId, setRunId] = React.useState(0)
    const [statuses, setStatuses] = React.useState<ChatSourceStatus[]>(() => SITES.map(() => 'pending'))
    const [running, setRunning] = React.useState(true)

    React.useEffect(() => {
        setStatuses(SITES.map(() => 'pending'))
        setRunning(true)
        const setAt = (index: number, status: ChatSourceStatus): void =>
            setStatuses((prev) => prev.map((value, i) => (i === index ? status : value)))
        const timers = TIMELINE.flatMap(({ discover, finish }, index) => [
            setTimeout(() => setAt(index, 'loading'), discover),
            setTimeout(() => setAt(index, 'done'), finish),
        ])
        const last = Math.max(...TIMELINE.map((t) => t.finish))
        timers.push(setTimeout(() => setRunning(false), last + 800))
        return () => timers.forEach(clearTimeout)
    }, [runId])

    return (
        <div className="flex w-[460px] flex-col gap-4">
            <WebSearch statuses={statuses} running={running} />
            <Button variant="outline" size="sm" className="self-start" onClick={() => setRunId((id) => id + 1)}>
                Replay
            </Button>
        </div>
    )
}

/**
 * The whole arc: rows are discovered, fetched, and land one by one, then the call settles. The app
 * owns the timing — the primitive never infers it.
 */
export const Live: Story = {
    render: () => <LiveSearch />,
}

/** Icons stay off the summary, but `SearchIcon` and friends still belong on the rows inside. */
export const SingleToolWithIconRows: Story = {
    render: () => (
        <div className="w-[460px]">
            <ChatToolCall status="done" defaultOpen>
                <ChatToolCallTrigger>
                    <ChatToolCallLabel>Searched 2 places</ChatToolCallLabel>
                </ChatToolCallTrigger>
                <ChatToolCallContent>
                    <ChatMarker>
                        <ChatMarkerIcon>
                            <SearchIcon />
                        </ChatMarkerIcon>
                        <ChatMarkerContent>Searched the web — 3 sources</ChatMarkerContent>
                    </ChatMarker>
                    <ChatMarker>
                        <ChatMarkerIcon>
                            <SearchIcon />
                        </ChatMarkerIcon>
                        <ChatMarkerContent>Searched the knowledge base — 1 result</ChatMarkerContent>
                    </ChatMarker>
                </ChatToolCallContent>
            </ChatToolCall>
        </div>
    ),
}
