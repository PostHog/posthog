import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useState } from 'react'

import {
    IconChevronLeft,
    IconChevronRight,
    IconComment,
    IconDocument,
    IconDownload,
    IconExpand45,
    IconGraph,
    IconDatabase,
    IconX,
} from '@posthog/icons'
import {
    Avatar,
    AvatarFallback,
    Badge,
    Button,
    Card,
    Heading,
    ResizableHandle,
    ResizablePanel,
    ResizablePanelGroup,
    Tabs,
    TabsList,
    TabsTrigger,
    Text,
    Textarea,
    TooltipProvider,
    cn,
} from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'

import { TodayShell } from './TodayShell'
import { TodayRailPane, todayShellLogic } from './todayShellLogic'

type ArtifactKind = 'report' | 'chart' | 'data'

interface MockArtifact {
    id: string
    name: string
    kind: ArtifactKind
    size: string
    session: string
    space: string
    author: string
    updated: string
    comments: number
    title?: string
    summary?: string
}

const ARTIFACTS: MockArtifact[] = [
    {
        id: 'a-report',
        name: 'trial-drop-report.md',
        kind: 'report',
        size: '6 KB',
        session: 'Investigate the drop in trial starts',
        space: 'checkout',
        author: 'Ada Lovelace',
        updated: '12m ago',
        comments: 2,
        title: 'Trial starts dropped at the plan picker',
        summary: 'Trial starts fell 18% week over week. The loss sits almost entirely at the plan picker step.',
    },
    {
        id: 'a-chart',
        name: 'trial-starts-by-step.png',
        kind: 'chart',
        size: '84 KB',
        session: 'Investigate the drop in trial starts',
        space: 'checkout',
        author: 'Ada Lovelace',
        updated: '14m ago',
        comments: 0,
    },
    {
        id: 'a-data',
        name: 'trial-starts-by-week.csv',
        kind: 'data',
        size: '3 KB',
        session: 'Investigate the drop in trial starts',
        space: 'checkout',
        author: 'Ada Lovelace',
        updated: '15m ago',
        comments: 0,
    },
]

const OTHER_ARTIFACTS: MockArtifact[] = [
    {
        id: 'b-report',
        name: 'billing-webhook-retry-plan.md',
        kind: 'report',
        size: '4 KB',
        session: 'Add a retry to the billing webhook',
        space: 'checkout',
        author: 'John Baker',
        updated: '2h ago',
        comments: 1,
        title: 'Retry plan for the billing webhook',
        summary: 'Retry three times with a backoff of 1, 4 and 16 seconds, then report the failure.',
    },
    {
        id: 'b-chart',
        name: 'webhook-failures-by-hour.png',
        kind: 'chart',
        size: '61 KB',
        session: 'Add a retry to the billing webhook',
        space: 'checkout',
        author: 'John Baker',
        updated: '2h ago',
        comments: 0,
    },
]

const KIND_LABEL: Record<ArtifactKind, string> = { report: 'Report', chart: 'Image', data: 'Data' }

function ArtifactIcon({ kind, className }: { kind: ArtifactKind; className?: string }): JSX.Element {
    const Icon = kind === 'report' ? IconDocument : kind === 'chart' ? IconGraph : IconDatabase
    return <Icon className={cn('shrink-0', className)} />
}

const SPACES = [
    {
        id: 'space-me',
        name: 'me',
        channel_type: 'private',
        github_integration: null,
        repositories: [],
        auto_archive_after_days: null,
        created_at: '2026-09-01T09:00:00Z',
        starred: true,
        system_role: 'personal',
    },
    {
        id: 'space-checkout',
        name: 'checkout',
        channel_type: 'public',
        github_integration: null,
        repositories: ['example-org/web'],
        auto_archive_after_days: null,
        created_at: '2026-09-02T09:00:00Z',
        starred: true,
        system_role: null,
    },
]

const SESSIONS = [
    {
        id: 'task-trials',
        title: 'Investigate the drop in trial starts',
        archived: false,
        channel: 'space-checkout',
        last_activity_at: '2026-09-28T18:15:00Z',
        latest_run: { id: 'run-trials', status: 'completed', environment: 'cloud', output: null },
        description_preview: 'Trial starts dropped last week. Find the step where people leave.',
        repository: null,
        created_by: { id: 1, first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' },
    },
    {
        id: 'task-webhook',
        title: 'Add a retry to the billing webhook',
        archived: false,
        channel: 'space-checkout',
        last_activity_at: '2026-09-28T16:05:00Z',
        latest_run: { id: 'run-webhook', status: 'completed', environment: 'cloud', output: null },
        description_preview: 'Retry the billing webhook three times with a backoff.',
        repository: 'example-org/web',
        created_by: { id: 2, first_name: 'John', last_name: 'Baker', email: 'john@example.com' },
    },
]

function useOpenPane(pane: TodayRailPane): void {
    const { pickPane } = useActions(todayShellLogic)
    useEffect(() => {
        pickPane(pane)
    }, [pane, pickPane])
}

function WebLayout({ pane = 'spaces', children }: { pane?: TodayRailPane; children: ReactNode }): JSX.Element {
    useOpenPane(pane)
    const { user } = useValues(userLogic)
    return (
        <TooltipProvider>
            <div className="TodayAppLayout Today flex h-screen w-full overflow-hidden">
                {user ? <TodayShell /> : null}
                <div className="main-content-container flex flex-1 min-w-0 overflow-hidden rounded border border-primary my-1 mr-1 bg-[var(--color-bg-primary)]">
                    <main className="flex flex-1 min-w-0 flex-col overflow-hidden" data-quill>
                        {children}
                    </main>
                </div>
            </div>
        </TooltipProvider>
    )
}

function SessionHeader({ actions, tabs }: { actions?: ReactNode; tabs?: ReactNode }): JSX.Element {
    return (
        <div className="shrink-0 border-b border-border px-6 pt-4">
            <div className="flex items-center gap-2 pb-3">
                <Text size="xs" variant="muted">
                    checkout
                </Text>
                <Text size="xs" variant="muted">
                    /
                </Text>
                <Heading size="sm" className="min-w-0 truncate">
                    Investigate the drop in trial starts
                </Heading>
                <Badge variant="success">Done</Badge>
                <div className="ml-auto flex items-center gap-2">{actions}</div>
            </div>
            {tabs}
        </div>
    )
}

function UserMessage({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="flex justify-end">
            <div className="max-w-[80%] rounded-lg bg-[var(--today-soft)] px-3 py-2 text-sm">{children}</div>
        </div>
    )
}

function AgentMessage({ children }: { children: ReactNode }): JSX.Element {
    return <div className="flex flex-col gap-2 text-sm leading-relaxed">{children}</div>
}

function ToolRow({ label }: { label: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" className="flex items-center gap-1.5">
            <IconChevronRight className="size-3" />
            {label}
        </Text>
    )
}

function ArtifactChip({
    artifact,
    active,
    onClick,
}: {
    artifact: MockArtifact
    active?: boolean
    onClick?: () => void
}): JSX.Element {
    return (
        <Button variant={active ? 'secondary' : 'outline'} size="sm" onClick={onClick}>
            <ArtifactIcon kind={artifact.kind} />
            {artifact.name}
        </Button>
    )
}

function ArtifactCard({ artifact, onOpen }: { artifact: MockArtifact; onOpen?: () => void }): JSX.Element {
    return (
        <Card size="sm" className="flex-row items-center gap-3 px-3 py-2">
            <div className="flex size-9 items-center justify-center rounded bg-[var(--today-soft)]">
                <ArtifactIcon kind={artifact.kind} className="size-4" />
            </div>
            <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-medium">{artifact.name}</span>
                <Text size="xs" variant="muted">
                    {`${KIND_LABEL[artifact.kind]} · ${artifact.size}`}
                </Text>
            </div>
            <Button variant="outline" size="sm" onClick={onOpen}>
                Open
            </Button>
            <Button variant="default" size="icon-sm" aria-label={`Download ${artifact.name}`}>
                <IconDownload />
            </Button>
        </Card>
    )
}

function Thread({ artifactSlot }: { artifactSlot?: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-5">
            <UserMessage>
                Trial starts dropped last week. Find the step where people leave and write it up for the team.
            </UserMessage>
            <AgentMessage>
                <ToolRow label="Ran 4 queries on trial funnel events" />
                <ToolRow label="Watched 6 session recordings" />
                <p>
                    Trial starts fell 18% week over week. Almost all of the loss is at the plan picker step, which
                    changed in the release on Tuesday. The new layout pushes the start trial button below the fold on
                    laptop screens.
                </p>
                <p>I wrote a short report, a chart of each funnel step, and the weekly numbers as a CSV.</p>
                {artifactSlot}
            </AgentMessage>
        </div>
    )
}

function Composer(): JSX.Element {
    return (
        <div className="shrink-0 px-6 pb-4 pt-2">
            <div className="mx-auto max-w-3xl rounded-lg border border-border bg-card px-3 py-2">
                <Text size="sm" variant="muted">
                    Ask a follow-up
                </Text>
                <div className="flex justify-end pt-4">
                    <Button size="sm">Send</Button>
                </div>
            </div>
        </div>
    )
}

function ReportPreview(): JSX.Element {
    return (
        <article className="flex flex-col gap-3 text-sm leading-relaxed">
            <Heading size="md">Trial starts dropped at the plan picker</Heading>
            <Text size="xs" variant="muted">
                Written by the agent · Sep 28
            </Text>
            <Heading size="sm">What happened</Heading>
            <p>
                Trial starts fell 18% week over week. The loss sits almost entirely at the plan picker step. Other steps
                did not change.
            </p>
            <Heading size="sm">Why</Heading>
            <ul className="list-disc pl-5">
                <li>The release on Tuesday moved the start trial button below the fold at 1366 × 768.</li>
                <li>Recordings show people scroll the plan table, then leave without a click.</li>
                <li>Wide screens do not show the drop.</li>
            </ul>
            <Heading size="sm">Next steps</Heading>
            <ul className="list-disc pl-5">
                <li>Pin the button to the top of the plan table.</li>
                <li>Run an A/B test on the change for one week.</li>
            </ul>
        </article>
    )
}

const FUNNEL = [
    { step: 'Pricing', before: 100, after: 100 },
    { step: 'Plan picker', before: 62, after: 44 },
    { step: 'Details', before: 48, after: 35 },
    { step: 'Trial started', before: 41, after: 30 },
]

function ChartPreview({ compact }: { compact?: boolean }): JSX.Element {
    const height = compact ? 90 : 220
    return (
        <div className="flex flex-col gap-2">
            {!compact && <Heading size="sm">Conversion by funnel step</Heading>}
            <svg viewBox={`0 0 400 ${height + 24}`} className="w-full" role="img" aria-label="Funnel chart">
                {FUNNEL.map((row, i) => {
                    const x = 20 + i * 95
                    const hBefore = (row.before / 100) * height
                    const hAfter = (row.after / 100) * height
                    return (
                        <g key={row.step}>
                            <rect x={x} y={height - hBefore} width={34} height={hBefore} rx={2} fill="#b8b8b2" />
                            <rect x={x + 38} y={height - hAfter} width={34} height={hAfter} rx={2} fill="#1d4aff" />
                            {!compact && (
                                <text x={x + 36} y={height + 16} textAnchor="middle" fontSize="11" fill="currentColor">
                                    {row.step}
                                </text>
                            )}
                        </g>
                    )
                })}
            </svg>
            {!compact && (
                <Text size="xs" variant="muted">
                    Gray: week of Sep 14. Blue: week of Sep 21.
                </Text>
            )}
        </div>
    )
}

const WEEKS = [
    ['Aug 31', '1,204', '41%'],
    ['Sep 7', '1,188', '40%'],
    ['Sep 14', '1,231', '41%'],
    ['Sep 21', '1,009', '30%'],
]

function DataPreview({ compact }: { compact?: boolean }): JSX.Element {
    const rows = compact ? WEEKS.slice(0, 3) : WEEKS
    return (
        <table className="w-full text-left text-xs">
            <thead>
                <tr className="border-b border-border text-muted-foreground">
                    <th className="py-1.5 pr-3 font-medium">week</th>
                    <th className="py-1.5 pr-3 font-medium">trial_starts</th>
                    <th className="py-1.5 font-medium">conversion</th>
                </tr>
            </thead>
            <tbody>
                {rows.map((row) => (
                    <tr key={row[0]} className="border-b border-border last:border-0">
                        {row.map((cell) => (
                            <td key={cell} className="py-1.5 pr-3 font-mono">
                                {cell}
                            </td>
                        ))}
                    </tr>
                ))}
            </tbody>
        </table>
    )
}

function ArtifactPreview({ artifact, compact }: { artifact: MockArtifact; compact?: boolean }): JSX.Element {
    if (artifact.kind === 'chart') {
        return <ChartPreview compact={compact} />
    }
    if (artifact.kind === 'data') {
        return <DataPreview compact={compact} />
    }
    if (compact) {
        return (
            <div className="flex flex-col gap-1 text-xs">
                <span className="font-semibold">{artifact.title}</span>
                <Text size="xs" variant="muted" className="line-clamp-4">
                    {artifact.summary}
                </Text>
            </div>
        )
    }
    return <ReportPreview />
}

function ArtifactToolbar({ artifact, onClose }: { artifact: MockArtifact; onClose?: () => void }): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            <Button variant="outline" size="sm">
                <IconComment />
                {artifact.comments > 0 ? `${artifact.comments} comments` : 'Comment'}
            </Button>
            <Button variant="default" size="icon-sm" aria-label="Download">
                <IconDownload />
            </Button>
            <Button variant="default" size="icon-sm" aria-label="Open full page">
                <IconExpand45 />
            </Button>
            {onClose && (
                <Button variant="default" size="icon-sm" aria-label="Close panel" onClick={onClose}>
                    <IconX />
                </Button>
            )}
        </div>
    )
}

function OptionSidePanel(): JSX.Element {
    const [activeId, setActiveId] = useState(ARTIFACTS[0].id)
    const active = ARTIFACTS.find((artifact) => artifact.id === activeId) ?? ARTIFACTS[0]
    return (
        <WebLayout>
            <SessionHeader
                actions={
                    <Button variant="outline" size="sm">
                        Open in PostHog Desktop
                    </Button>
                }
            />
            <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
                <ResizablePanel defaultSize="52%" minSize="30%">
                    <div className="flex h-full flex-col">
                        <div className="flex-1 overflow-y-auto px-6 py-5">
                            <Thread
                                artifactSlot={
                                    <div className="flex flex-wrap gap-2 pt-1">
                                        {ARTIFACTS.map((artifact) => (
                                            <ArtifactChip
                                                key={artifact.id}
                                                artifact={artifact}
                                                active={artifact.id === activeId}
                                                onClick={() => setActiveId(artifact.id)}
                                            />
                                        ))}
                                    </div>
                                }
                            />
                        </div>
                        <Composer />
                    </div>
                </ResizablePanel>
                <ResizableHandle withHandle />
                <ResizablePanel defaultSize="48%" minSize="30%">
                    <div className="flex h-full flex-col bg-card">
                        <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
                            <Tabs value={activeId} onValueChange={(value: string) => setActiveId(value)}>
                                <TabsList variant="line">
                                    {ARTIFACTS.map((artifact) => (
                                        <TabsTrigger key={artifact.id} value={artifact.id}>
                                            <ArtifactIcon kind={artifact.kind} />
                                            <span className="max-w-32 truncate">{artifact.name}</span>
                                        </TabsTrigger>
                                    ))}
                                </TabsList>
                            </Tabs>
                            <div className="ml-auto">
                                <ArtifactToolbar artifact={active} onClose={() => {}} />
                            </div>
                        </div>
                        <div className="flex-1 overflow-y-auto px-6 py-5">
                            <ArtifactPreview artifact={active} />
                        </div>
                    </div>
                </ResizablePanel>
            </ResizablePanelGroup>
        </WebLayout>
    )
}

function OptionInlineCards(): JSX.Element {
    return (
        <WebLayout>
            <SessionHeader
                actions={
                    <Button variant="outline" size="sm">
                        Open in PostHog Desktop
                    </Button>
                }
            />
            <div className="flex-1 overflow-y-auto px-6 py-5">
                <div className="mx-auto max-w-3xl">
                    <Thread
                        artifactSlot={
                            <div className="flex flex-col gap-2 pt-1">
                                {ARTIFACTS.map((artifact) => (
                                    <ArtifactCard key={artifact.id} artifact={artifact} />
                                ))}
                            </div>
                        }
                    />
                </div>
            </div>
            <Composer />
        </WebLayout>
    )
}

function CommentThread(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <Text size="sm" className="font-medium">
                Comments
            </Text>
            {[
                { who: 'JB', name: 'John Baker', text: 'Can we check this on mobile too?' },
                { who: 'AL', name: 'Ada Lovelace', text: 'Mobile is flat. I added a note to the report.' },
            ].map((comment) => (
                <div key={comment.text} className="flex gap-2">
                    <Avatar size="xs">
                        <AvatarFallback>{comment.who}</AvatarFallback>
                    </Avatar>
                    <div className="flex flex-col">
                        <Text size="xs" className="font-medium">
                            {comment.name}
                        </Text>
                        <Text size="sm">{comment.text}</Text>
                    </div>
                </div>
            ))}
            <Textarea placeholder="Add a comment" rows={2} />
        </div>
    )
}

function OptionFocusView(): JSX.Element {
    const artifact = ARTIFACTS[0]
    return (
        <WebLayout>
            <div className="flex shrink-0 items-center gap-2 border-b border-border px-6 py-3">
                <Button variant="default" size="sm">
                    <IconChevronLeft />
                    Investigate the drop in trial starts
                </Button>
                <Text size="xs" variant="muted">
                    /
                </Text>
                <ArtifactIcon kind={artifact.kind} />
                <Heading size="sm">{artifact.name}</Heading>
                <Text size="xs" variant="muted">
                    {`1 of ${ARTIFACTS.length}`}
                </Text>
                <Button variant="default" size="icon-sm" aria-label="Previous artifact">
                    <IconChevronLeft />
                </Button>
                <Button variant="default" size="icon-sm" aria-label="Next artifact">
                    <IconChevronRight />
                </Button>
                <div className="ml-auto flex items-center gap-1">
                    <Button variant="default" size="icon-sm" aria-label="Download">
                        <IconDownload />
                    </Button>
                    <Button variant="outline" size="sm">
                        Share
                    </Button>
                </div>
            </div>
            <div className="flex min-h-0 flex-1">
                <div className="flex-1 overflow-y-auto px-10 py-8">
                    <div className="mx-auto max-w-2xl">
                        <ReportPreview />
                    </div>
                </div>
                <aside className="w-72 shrink-0 overflow-y-auto border-l border-border bg-card px-4 py-4">
                    <CommentThread />
                </aside>
            </div>
        </WebLayout>
    )
}

function GalleryCard({ artifact, showSession }: { artifact: MockArtifact; showSession?: boolean }): JSX.Element {
    return (
        <Card size="sm" className="gap-0 overflow-hidden p-0">
            <div className="h-32 overflow-hidden border-b border-border bg-background px-3 py-3">
                <ArtifactPreview artifact={artifact} compact />
            </div>
            <div className="flex flex-col gap-0.5 px-3 py-2">
                <span className="flex min-w-0 items-center gap-1.5 font-medium">
                    <ArtifactIcon kind={artifact.kind} />
                    <span className="truncate">{artifact.name}</span>
                </span>
                <Text size="xs" variant="muted" className="truncate">
                    {showSession
                        ? `${artifact.session} · ${artifact.updated}`
                        : `${KIND_LABEL[artifact.kind]} · ${artifact.size} · ${artifact.updated}`}
                </Text>
            </div>
        </Card>
    )
}

function OptionSessionTabs(): JSX.Element {
    return (
        <WebLayout>
            <SessionHeader
                actions={
                    <Button variant="outline" size="sm">
                        Open in PostHog Desktop
                    </Button>
                }
                tabs={
                    <Tabs value="artifacts">
                        <TabsList variant="line">
                            <TabsTrigger value="conversation">Conversation</TabsTrigger>
                            <TabsTrigger value="artifacts">
                                Artifacts <Badge>{ARTIFACTS.length}</Badge>
                            </TabsTrigger>
                        </TabsList>
                    </Tabs>
                }
            />
            <div className="flex-1 overflow-y-auto px-6 py-5">
                <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
                    {ARTIFACTS.map((artifact) => (
                        <GalleryCard key={artifact.id} artifact={artifact} />
                    ))}
                </div>
            </div>
        </WebLayout>
    )
}

function OptionSpaceTab(): JSX.Element {
    const groups = [
        { session: ARTIFACTS[0].session, items: ARTIFACTS },
        { session: OTHER_ARTIFACTS[0].session, items: OTHER_ARTIFACTS },
    ]
    return (
        <WebLayout>
            <div className="shrink-0 px-6 pt-4">
                <Heading size="md" className="pb-3">
                    checkout
                </Heading>
                <Tabs value="artifacts">
                    <TabsList variant="line">
                        <TabsTrigger value="feed">Feed</TabsTrigger>
                        <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
                        <TabsTrigger value="settings">Settings</TabsTrigger>
                    </TabsList>
                </Tabs>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-5">
                <div className="flex max-w-5xl flex-col gap-6">
                    {groups.map((group) => (
                        <section key={group.session} className="flex flex-col gap-2">
                            <Text size="sm" className="font-medium">
                                {group.session}
                            </Text>
                            <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-3">
                                {group.items.map((artifact) => (
                                    <GalleryCard key={artifact.id} artifact={artifact} />
                                ))}
                            </div>
                        </section>
                    ))}
                </div>
            </div>
        </WebLayout>
    )
}

const meta: Meta = {
    title: 'Mockups/Today/Artifacts on web',
    tags: ['test-skip'],
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/task_channels/': SPACES,
                '/api/projects/:team_id/task_channels/:id/': (req) => [
                    200,
                    SPACES.find((space) => space.id === req.params.id) ?? SPACES[0],
                ],
                '/api/projects/:team_id/tasks/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const results = params.get('pinned') ? [] : SESSIONS
                    return [200, { results, count: results.length, next: null, previous: null }]
                },
                '/api/environments/:team_id/conversations/': { results: [], next: null },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-28 18:30:00',
        pageUrl: urls.aiTask('task-trials'),
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
    },
}
export default meta

type Story = StoryObj<{}>

export const OptionASidePanel: Story = { render: () => <OptionSidePanel /> }

export const OptionBInlineCards: Story = { render: () => <OptionInlineCards /> }

export const OptionBFocusView: Story = { render: () => <OptionFocusView /> }

export const OptionCSessionTabs: Story = { render: () => <OptionSessionTabs /> }

export const OptionDSpaceTab: Story = {
    parameters: { pageUrl: urls.taskSpace('space-checkout') },
    render: () => <OptionSpaceTab />,
}
