import type { Meta, StoryObj } from '@storybook/react'

import { CheckIcon, FileIcon, PencilIcon, SearchIcon, TerminalIcon } from 'lucide-react'
import * as React from 'react'

import { ChatMarker, ChatMarkerContent, ChatMarkerIcon, ChatMarkerValue } from './chat-marker'
import { ChatSource, ChatSourceList, ChatSourceTitle, ChatSourceUrl, type ChatSourceStatus } from './chat-source'
import { Button } from '../button'
import { Spinner } from '../spinner'

const meta = {
    title: 'Primitives/Chat/ChatMarker',
    component: ChatMarker,
    tags: ['autodocs'],
} satisfies Meta<typeof ChatMarker>

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

/** The three flat variants — a settled note, no body, nothing to open. */
export const Variants = {
    render: () => (
        <div className="flex w-[420px] flex-col gap-4">
            <ChatMarker>
                <ChatMarkerIcon>
                    <CheckIcon />
                </ChatMarkerIcon>
                <ChatMarkerContent>Explored 4 files</ChatMarkerContent>
            </ChatMarker>
            <ChatMarker variant="border">
                <ChatMarkerIcon>
                    <SearchIcon />
                </ChatMarkerIcon>
                <ChatMarkerContent>Searched the workspace</ChatMarkerContent>
            </ChatMarker>
            <ChatMarker variant="separator">
                <ChatMarkerContent>Context compacted</ChatMarkerContent>
            </ChatMarker>
        </div>
    ),
} satisfies Story

/** `status="running"` shimmers the content. Pair it with a Spinner for the icon. */
export const Live = {
    render: () => (
        <div className="w-[420px]">
            <ChatMarker status="running">
                <ChatMarkerIcon>
                    <Spinner />
                </ChatMarkerIcon>
                <ChatMarkerContent>Editing components/thread.tsx…</ChatMarkerContent>
            </ChatMarker>
        </div>
    ),
} satisfies Story

/**
 * One tool call: `status` plus the argument it acted on. The value is quoted by CSS, and goes
 * foreground once the call settles — that's the fact worth keeping.
 */
export const ToolCall = {
    render: () => (
        <div className="flex w-[420px] flex-col gap-4">
            <ChatMarker status="running">
                <ChatMarkerIcon>
                    <SearchIcon />
                </ChatMarkerIcon>
                <ChatMarkerContent>
                    Searching
                    <ChatMarkerValue>{QUERY}</ChatMarkerValue>
                </ChatMarkerContent>
            </ChatMarker>
            <ChatMarker status="done">
                <ChatMarkerIcon>
                    <TerminalIcon />
                </ChatMarkerIcon>
                <ChatMarkerContent>
                    Ran
                    <ChatMarkerValue>pnpm build</ChatMarkerValue>
                </ChatMarkerContent>
            </ChatMarker>
            <ChatMarker status="error">
                <ChatMarkerIcon>
                    <TerminalIcon />
                </ChatMarkerIcon>
                <ChatMarkerContent>
                    Couldn’t run
                    <ChatMarkerValue>pnpm test</ChatMarkerValue>
                </ChatMarkerContent>
            </ChatMarker>
        </div>
    ),
} satisfies Story

/**
 * A group: pass `body` and drop the icon. The row is the joined-up summary and the calls behind it
 * are markers of their own — no single icon is honest about several tools at once. The chevron hugs
 * the summary and only shows on hover, so a transcript of these isn't a wall of controls.
 */
export const Group = {
    render: () => (
        <div className="flex w-[420px] flex-col gap-4">
            <ChatMarker
                defaultOpen
                status="done"
                body={
                    <>
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
                    </>
                }
            >
                <ChatMarkerContent>Read 2 files · Edited 1 file · Ran 1 command</ChatMarkerContent>
            </ChatMarker>

            <ChatMarker
                defaultOpen={false}
                status="done"
                body={
                    <ChatMarker>
                        <ChatMarkerIcon>
                            <TerminalIcon />
                        </ChatMarkerIcon>
                        <ChatMarkerContent>pnpm build — exit 0</ChatMarkerContent>
                    </ChatMarker>
                }
            >
                <ChatMarkerContent>Ran 1 command (collapsed by default)</ChatMarkerContent>
            </ChatMarker>
        </div>
    ),
} satisfies Story

function WebSearch({ statuses, running }: { statuses: ChatSourceStatus[]; running: boolean }): React.ReactElement {
    return (
        <ChatMarker
            defaultOpen
            status={running ? 'running' : 'done'}
            body={
                <ChatSourceList>
                    {SITES.map((site, index) => (
                        <ChatSource key={site.url} status={statuses[index]} href={`https://${site.url}`}>
                            <ChatSourceTitle>{site.title}</ChatSourceTitle>
                            <ChatSourceUrl>{site.url}</ChatSourceUrl>
                        </ChatSource>
                    ))}
                </ChatSourceList>
            }
        >
            <ChatMarkerContent>
                {running ? 'Searching' : `Searched ${SITES.length} sources`}
                <ChatMarkerValue>{QUERY}</ChatMarkerValue>
            </ChatMarkerContent>
        </ChatMarker>
    )
}

/**
 * A tool that returned pages: fill the body with `ChatSourceList` instead of markers. Each row walks
 * its own fetch — dashed ring → globe → green check — and the app owns when it moves.
 */
export const WebSearchSources = {
    render: () => (
        <div className="w-[460px]">
            <WebSearch statuses={['pending', 'loading', 'done']} running />
        </div>
    ),
} satisfies Story

/**
 * An errored group tints its own row only. The rows inside keep their own outcomes — the one that
 * succeeded still reads as a success, because a group's status is not its children's.
 */
export const GroupError = {
    render: () => (
        <div className="w-[460px]">
            <ChatMarker
                defaultOpen
                status="error"
                body={
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
                }
            >
                <ChatMarkerContent>
                    Couldn’t search
                    <ChatMarkerValue>{QUERY}</ChatMarkerValue>
                </ChatMarkerContent>
            </ChatMarker>
        </div>
    ),
} satisfies Story

/** A source row without an href is static text — no hover fill, no out-arrow. */
export const SourcesWithoutLinks = {
    render: () => (
        <div className="w-[460px]">
            <ChatMarker
                defaultOpen
                status="done"
                body={
                    <ChatSourceList>
                        <ChatSource status="done">
                            <ChatSourceTitle>Internal runbook</ChatSourceTitle>
                            <ChatSourceUrl>indexed 2 days ago</ChatSourceUrl>
                        </ChatSource>
                    </ChatSourceList>
                }
            >
                <ChatMarkerContent>
                    Searched the knowledge base
                    <ChatMarkerValue>onboarding</ChatMarkerValue>
                </ChatMarkerContent>
            </ChatMarker>
        </div>
    ),
} satisfies Story

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
 * The whole arc: sources are discovered, fetched, and land one by one, then the call settles and the
 * shimmer stops. The app owns the timing — the primitive never infers it.
 */
export const Live_Search = {
    name: 'Live search',
    render: () => <LiveSearch />,
} satisfies Story
