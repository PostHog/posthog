import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useState } from 'react'

import {
    IconArrowLeft,
    IconArrowRight,
    IconChevronLeft,
    IconChevronRight,
    IconComment,
    IconDatabase,
    IconDocument,
    IconDownload,
    IconEllipsis,
    IconExternal,
    IconGraph,
    IconGridMasonry,
    IconList,
    IconSearch,
    IconShare,
} from '@posthog/icons'
import {
    Avatar,
    AvatarFallback,
    Button,
    ChatBubble,
    ChatBubbleContent,
    ChatMarker,
    ChatMarkerContent,
    ChatMarkerIcon,
    ChatMarkerValue,
    Dot,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Tabs,
    TabsList,
    TabsTrigger,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'

import { TodayShell } from './TodayShell'
import { TodayRailPane, todayShellLogic } from './todayShellLogic'

type ArtifactKind = 'report' | 'chart' | 'data'
type SessionTab = 'conversation' | 'artifacts'
type KindFilter = 'all' | ArtifactKind
type GalleryView = 'grid' | 'list'

interface MockArtifact {
    id: string
    name: string
    kind: ArtifactKind
    size: string
    updated: string
    comments: number
    title: string
    summary: string
}

const ARTIFACTS: MockArtifact[] = [
    {
        id: 'a-report',
        name: 'trial-drop-report.md',
        kind: 'report',
        size: '6 KB',
        updated: '12m ago',
        comments: 2,
        title: 'Trial starts dropped at the plan picker',
        summary:
            'Trial starts fell 18% week over week. The loss sits almost entirely at the plan picker step, which changed in the release on Tuesday.',
    },
    {
        id: 'a-chart',
        name: 'trial-starts-by-step.png',
        kind: 'chart',
        size: '84 KB',
        updated: '14m ago',
        comments: 0,
        title: 'Conversion by funnel step',
        summary: 'Each funnel step, this week against last week.',
    },
    {
        id: 'a-data',
        name: 'trial-starts-by-week.csv',
        kind: 'data',
        size: '3 KB',
        updated: '15m ago',
        comments: 1,
        title: 'Trial starts by week',
        summary: 'Weekly trial starts and conversion for the last four weeks.',
    },
]

const KIND_LABEL: Record<ArtifactKind, string> = { report: 'Report', chart: 'Image', data: 'CSV' }

const FUNNEL = [
    { step: 'Pricing', before: 100, after: 100 },
    { step: 'Plan picker', before: 62, after: 44 },
    { step: 'Details', before: 48, after: 35 },
    { step: 'Trial started', before: 41, after: 30 },
]

const WEEKS = [
    { week: 'Aug 31', starts: '1,204', conversion: '41%' },
    { week: 'Sep 7', starts: '1,188', conversion: '40%' },
    { week: 'Sep 14', starts: '1,231', conversion: '41%' },
    { week: 'Sep 21', starts: '1,009', conversion: '30%' },
]

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

function ArtifactIcon({ kind, className }: { kind: ArtifactKind; className?: string }): JSX.Element {
    const Icon = kind === 'report' ? IconDocument : kind === 'chart' ? IconGraph : IconDatabase
    return <Icon className={cn('shrink-0', className)} />
}

function IconAction({
    label,
    onClick,
    children,
}: {
    label: string
    onClick?: () => void
    children: ReactNode
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={<Button variant="default" size="icon-sm" aria-label={label} onClick={onClick} />}
            >
                {children}
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
        </Tooltip>
    )
}

function useOpenPane(pane: TodayRailPane): void {
    const { pickPane } = useActions(todayShellLogic)
    useEffect(() => {
        pickPane(pane)
    }, [pane, pickPane])
}

function WebLayout({ children }: { children: ReactNode }): JSX.Element {
    useOpenPane('spaces')
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

function SessionHeader({
    tab,
    onTabChange,
    artifactCount,
}: {
    tab: SessionTab
    onTabChange: (tab: SessionTab) => void
    artifactCount: number
}): JSX.Element {
    return (
        <header className="shrink-0 border-b border-border px-6 pt-5">
            <div className="flex flex-wrap items-start gap-3">
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                    <Text size="xs" variant="muted" className="flex items-center gap-1">
                        <span># checkout</span>
                        <IconChevronRight className="size-3" />
                        <span>Session</span>
                    </Text>
                    <Heading size="lg" render={<h1 />} className="truncate">
                        Investigate the drop in trial starts
                    </Heading>
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <Avatar size="xs">
                            <AvatarFallback>AL</AvatarFallback>
                        </Avatar>
                        <Text size="xs">Ada Lovelace</Text>
                        <Text size="xs" variant="muted">
                            Started Sep 28 at 5:42 PM
                        </Text>
                        <span className="flex items-center gap-1.5">
                            <Dot variant="success" />
                            <Text size="xs" variant="muted">
                                Done
                            </Text>
                        </span>
                    </div>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                    <Button variant="outline" size="sm">
                        <IconShare />
                        Share
                    </Button>
                    <Button variant="outline" size="sm">
                        Open in PostHog Desktop
                    </Button>
                    <IconAction label="More actions">
                        <IconEllipsis />
                    </IconAction>
                </div>
            </div>
            <Tabs value={tab} onValueChange={(value: string) => onTabChange(value as SessionTab)} className="pt-3">
                <TabsList variant="line">
                    <TabsTrigger value="conversation">Conversation</TabsTrigger>
                    <TabsTrigger value="artifacts">
                        Artifacts
                        {artifactCount > 0 && (
                            <Text size="xs" variant="muted" render={<span />}>
                                {artifactCount}
                            </Text>
                        )}
                    </TabsTrigger>
                </TabsList>
            </Tabs>
        </header>
    )
}

function ReportMiniature({ artifact }: { artifact: MockArtifact }): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            <span className="text-xs font-semibold leading-snug">{artifact.title}</span>
            <span className="text-xxs leading-relaxed text-muted-foreground">{artifact.summary}</span>
            <span className="pt-1 text-xxs font-semibold">Why</span>
            <span className="text-xxs leading-relaxed text-muted-foreground">
                The release on Tuesday moved the start trial button below the fold on laptop screens.
            </span>
            <span className="pt-1 text-xxs font-semibold">Next steps</span>
            <span className="text-xxs leading-relaxed text-muted-foreground">
                1. Pin the start trial button to the top of the plan table.
            </span>
            <span className="text-xxs leading-relaxed text-muted-foreground">
                2. Run an A/B test on the change for one week.
            </span>
        </div>
    )
}

function ChartMiniature(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <span className="text-xxs font-semibold">Conversion by funnel step</span>
            <svg viewBox="0 0 200 80" className="w-full" aria-hidden>
                <line x1="0" y1="79.5" x2="200" y2="79.5" stroke="var(--color-graph-axis-line)" />
                {FUNNEL.map((row, i) => {
                    const x = 8 + i * 50
                    return (
                        <g key={row.step}>
                            <rect
                                x={x}
                                y={80 - row.before * 0.76}
                                width={16}
                                height={row.before * 0.76}
                                rx={1.5}
                                fill="var(--data-color-1)"
                                fillOpacity={0.28}
                            />
                            <rect
                                x={x + 18}
                                y={80 - row.after * 0.76}
                                width={16}
                                height={row.after * 0.76}
                                rx={1.5}
                                fill="var(--data-color-1)"
                            />
                        </g>
                    )
                })}
            </svg>
        </div>
    )
}

function DataMiniature(): JSX.Element {
    return (
        <div className="flex flex-col overflow-hidden rounded-sm border border-border font-mono text-xxs">
            <div className="grid grid-cols-3 border-b border-border bg-[var(--today-soft)] px-1.5 py-1 text-muted-foreground">
                <span>week</span>
                <span>trial_starts</span>
                <span>conversion</span>
            </div>
            {WEEKS.map((row) => (
                <div key={row.week} className="grid grid-cols-3 border-b border-border px-1.5 py-1 last:border-0">
                    <span>{row.week}</span>
                    <span>{row.starts}</span>
                    <span>{row.conversion}</span>
                </div>
            ))}
        </div>
    )
}

function ArtifactMiniature({ artifact }: { artifact: MockArtifact }): JSX.Element {
    if (artifact.kind === 'chart') {
        return <ChartMiniature />
    }
    if (artifact.kind === 'data') {
        return <DataMiniature />
    }
    return <ReportMiniature artifact={artifact} />
}

function ArtifactSheet({ artifact, className }: { artifact: MockArtifact; className?: string }): JSX.Element {
    return (
        <div className={cn('relative overflow-hidden bg-[var(--today-soft)]', className)}>
            <div className="absolute inset-x-5 top-4 -bottom-2 overflow-hidden rounded-md border border-border bg-card px-3.5 pt-3 text-left text-card-foreground shadow-sm transition-transform duration-200 group-hover:-translate-y-1 motion-reduce:transition-none">
                <ArtifactMiniature artifact={artifact} />
            </div>
        </div>
    )
}

function CommentCount({ count }: { count: number }): JSX.Element | null {
    if (count === 0) {
        return null
    }
    return (
        <Text size="xs" variant="muted" render={<span />} className="flex items-center gap-1">
            <IconComment className="size-3.5" />
            <span>{count}</span>
        </Text>
    )
}

function FeaturedArtifact({ artifact, onOpen }: { artifact: MockArtifact; onOpen: () => void }): JSX.Element {
    return (
        <article className="grid overflow-hidden rounded-lg border border-border bg-card text-card-foreground @min-[44rem]/artifacts:grid-cols-5">
            <button
                type="button"
                onClick={onOpen}
                aria-label={`Open ${artifact.name}`}
                className="group @min-[44rem]/artifacts:col-span-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30"
            >
                <ArtifactSheet
                    artifact={artifact}
                    className="h-52 border-b border-border @min-[44rem]/artifacts:h-full @min-[44rem]/artifacts:min-h-56 @min-[44rem]/artifacts:border-b-0 @min-[44rem]/artifacts:border-r"
                />
            </button>
            <div className="flex flex-col gap-3 p-5 @min-[44rem]/artifacts:col-span-2">
                <Text size="xs" variant="muted" className="flex items-center gap-1.5">
                    <ArtifactIcon kind={artifact.kind} className="size-3.5" />
                    <span className="truncate">{artifact.name}</span>
                </Text>
                <Heading size="base" render={<h2 />}>
                    {artifact.title}
                </Heading>
                <Text size="sm" variant="muted" className="line-clamp-3">
                    {artifact.summary}
                </Text>
                <div className="mt-auto flex flex-wrap items-center gap-2 pt-2">
                    <Button variant="primary" size="sm" onClick={onOpen}>
                        Open report
                    </Button>
                    <Button variant="outline" size="sm">
                        <IconDownload />
                        Download
                    </Button>
                    <span className="ml-auto flex items-center gap-2">
                        <CommentCount count={artifact.comments} />
                        <Text size="xs" variant="muted">
                            {artifact.updated}
                        </Text>
                    </span>
                </div>
            </div>
        </article>
    )
}

function ArtifactTile({ artifact, onOpen }: { artifact: MockArtifact; onOpen: () => void }): JSX.Element {
    return (
        <button
            type="button"
            onClick={onOpen}
            className="group flex flex-col overflow-hidden rounded-lg border border-border bg-card text-left text-card-foreground transition-colors hover:border-foreground/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 motion-reduce:transition-none"
        >
            <ArtifactSheet artifact={artifact} className="aspect-video w-full border-b border-border" />
            <div className="flex w-full items-start gap-2 px-3 py-2.5">
                <ArtifactIcon kind={artifact.kind} className="mt-0.5 size-4 text-muted-foreground" />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <Text size="sm" className="truncate font-medium">
                        {artifact.name}
                    </Text>
                    <Text size="xs" variant="muted">
                        {`${KIND_LABEL[artifact.kind]} · ${artifact.size} · ${artifact.updated}`}
                    </Text>
                </div>
                <CommentCount count={artifact.comments} />
            </div>
        </button>
    )
}

function ArtifactRows({
    artifacts,
    onOpen,
    size = 'sm',
}: {
    artifacts: MockArtifact[]
    onOpen: (id: string) => void
    size?: 'sm' | 'xs'
}): JSX.Element {
    return (
        <ItemGroup combined>
            {artifacts.map((artifact) => (
                <Item
                    key={artifact.id}
                    size={size}
                    variant="outline"
                    className="hover:bg-fill-hover"
                    render={<button type="button" onClick={() => onOpen(artifact.id)} />}
                >
                    <ItemMedia variant="icon">
                        <ArtifactIcon kind={artifact.kind} />
                    </ItemMedia>
                    <ItemContent>
                        <ItemTitle>{artifact.name}</ItemTitle>
                        <ItemDescription>{`${KIND_LABEL[artifact.kind]} · ${artifact.size} · ${artifact.updated}`}</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <CommentCount count={artifact.comments} />
                        <IconChevronRight className="size-4 text-muted-foreground" />
                    </ItemActions>
                </Item>
            ))}
        </ItemGroup>
    )
}

function GalleryToolbar({
    filter,
    onFilterChange,
    view,
    onViewChange,
}: {
    filter: KindFilter
    onFilterChange: (filter: KindFilter) => void
    view: GalleryView
    onViewChange: (view: GalleryView) => void
}): JSX.Element {
    const counts: Record<KindFilter, number> = {
        all: ARTIFACTS.length,
        report: ARTIFACTS.filter((artifact) => artifact.kind === 'report').length,
        chart: ARTIFACTS.filter((artifact) => artifact.kind === 'chart').length,
        data: ARTIFACTS.filter((artifact) => artifact.kind === 'data').length,
    }
    const filters: { value: KindFilter; label: string }[] = [
        { value: 'all', label: 'All' },
        { value: 'report', label: 'Reports' },
        { value: 'chart', label: 'Images' },
        { value: 'data', label: 'Data' },
    ]
    return (
        <div className="flex flex-wrap items-center gap-2">
            <ToggleGroup
                size="sm"
                spacing={1}
                value={[filter]}
                onValueChange={(value: string[]) => value[0] && onFilterChange(value[0] as KindFilter)}
            >
                {filters.map((option) => (
                    <ToggleGroupItem key={option.value} value={option.value}>
                        {option.label}
                        <span className="text-muted-foreground">{counts[option.value]}</span>
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            <div className="ml-auto flex items-center gap-1.5">
                <IconAction label="Search artifacts">
                    <IconSearch />
                </IconAction>
                <Button variant="outline" size="sm">
                    <IconDownload />
                    Download all
                </Button>
                <ToggleGroup
                    size="sm"
                    value={[view]}
                    onValueChange={(value: string[]) => value[0] && onViewChange(value[0] as GalleryView)}
                >
                    <ToggleGroupItem value="grid" aria-label="Grid view">
                        <IconGridMasonry />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="list" aria-label="List view">
                        <IconList />
                    </ToggleGroupItem>
                </ToggleGroup>
            </div>
        </div>
    )
}

function ArtifactsGallery({ onOpen }: { onOpen: (id: string) => void }): JSX.Element {
    const [filter, setFilter] = useState<KindFilter>('all')
    const [view, setView] = useState<GalleryView>('grid')
    const visible = ARTIFACTS.filter((artifact) => filter === 'all' || artifact.kind === filter)
    const [featured, ...rest] = visible
    const showFeatured = view === 'grid' && featured?.kind === 'report'
    const files = showFeatured ? rest : visible
    return (
        <div className="@container/artifacts flex-1 overflow-y-auto">
            <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-6">
                <GalleryToolbar filter={filter} onFilterChange={setFilter} view={view} onViewChange={setView} />
                {showFeatured && <FeaturedArtifact artifact={featured} onOpen={() => onOpen(featured.id)} />}
                {files.length > 0 && (
                    <section className="flex flex-col gap-3">
                        {showFeatured && (
                            <div className="flex items-baseline gap-2">
                                <Heading size="sm" render={<h2 />}>
                                    Supporting files
                                </Heading>
                                <Text size="xs" variant="muted">
                                    {files.length}
                                </Text>
                            </div>
                        )}
                        {view === 'grid' ? (
                            <div className="grid grid-cols-1 gap-4 @min-[34rem]/artifacts:grid-cols-2 @min-[56rem]/artifacts:grid-cols-3">
                                {files.map((artifact) => (
                                    <ArtifactTile
                                        key={artifact.id}
                                        artifact={artifact}
                                        onOpen={() => onOpen(artifact.id)}
                                    />
                                ))}
                            </div>
                        ) : (
                            <ArtifactRows artifacts={files} onOpen={onOpen} />
                        )}
                    </section>
                )}
            </div>
        </div>
    )
}

function ReportDocument(): JSX.Element {
    const stats = [
        { label: 'Trial starts', value: '1,009', change: '−18% on last week', negative: true },
        { label: 'Plan picker conversion', value: '44%', change: 'Was 62%', negative: true },
        { label: 'Other steps', value: 'Flat', change: 'Within 1 point', negative: false },
    ]
    return (
        <article className="flex flex-col gap-6 text-sm leading-relaxed">
            <header className="flex flex-col gap-2">
                <Text size="xs" variant="muted">
                    Report · Written by the agent for Ada Lovelace · Sep 28, 2026
                </Text>
                <Heading size="xl" render={<h1 />}>
                    Trial starts dropped at the plan picker
                </Heading>
                <Text size="base" variant="muted">
                    Trial starts fell 18% week over week. The loss sits almost entirely at the plan picker step.
                </Text>
            </header>
            <dl className="grid grid-cols-1 overflow-hidden rounded-lg border border-border @min-[32rem]/viewer:grid-cols-3">
                {stats.map((stat) => (
                    <div
                        key={stat.label}
                        className="flex flex-col gap-1 border-b border-border px-4 py-3 last:border-0 @min-[32rem]/viewer:border-b-0 @min-[32rem]/viewer:border-r"
                    >
                        <Text size="xs" variant="muted" render={<dt />}>
                            {stat.label}
                        </Text>
                        <dd className="flex flex-col">
                            <span className="text-xl font-semibold tabular-nums">{stat.value}</span>
                            <Text size="xs" variant={stat.negative ? 'destructive' : 'muted'} render={<span />}>
                                {stat.change}
                            </Text>
                        </dd>
                    </div>
                ))}
            </dl>
            <section className="flex flex-col gap-2">
                <Heading size="base" render={<h2 />}>
                    What happened
                </Heading>
                <p>
                    The release on Tuesday changed the plan picker layout. The start trial button now sits below the
                    fold at 1366 × 768, the most common laptop size in this funnel. Wide screens do not show the drop.
                </p>
            </section>
            <figure className="flex flex-col gap-3 rounded-lg border border-border p-4">
                <ChartFigure />
                <Text size="xs" variant="muted" render={<figcaption />}>
                    From trial-starts-by-step.png
                </Text>
            </figure>
            <section className="flex flex-col gap-2">
                <Heading size="base" render={<h2 />}>
                    Why
                </Heading>
                <ul className="flex list-disc flex-col gap-1 pl-5">
                    <li>Recordings show people scroll the plan table, then leave without a click.</li>
                    <li>The drop starts on the day of the release and holds all week.</li>
                    <li>Mobile uses a different layout and did not change.</li>
                </ul>
            </section>
            <section className="flex flex-col gap-2">
                <Heading size="base" render={<h2 />}>
                    Next steps
                </Heading>
                <ol className="flex list-decimal flex-col gap-1 pl-5">
                    <li>Pin the start trial button to the top of the plan table.</li>
                    <li>Run an A/B test on the change for one week.</li>
                </ol>
            </section>
        </article>
    )
}

function ChartFigure(): JSX.Element {
    const height = 180
    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                <Heading size="sm" render={<h3 />}>
                    Conversion by funnel step
                </Heading>
                <div className="ml-auto flex items-center gap-3">
                    <Text size="xs" variant="muted" className="flex items-center gap-1.5">
                        <svg viewBox="0 0 8 8" className="size-2" aria-hidden>
                            <rect width="8" height="8" rx="2" fill="var(--data-color-1)" fillOpacity={0.28} />
                        </svg>
                        <span>Week of Sep 14</span>
                    </Text>
                    <Text size="xs" variant="muted" className="flex items-center gap-1.5">
                        <svg viewBox="0 0 8 8" className="size-2" aria-hidden>
                            <rect width="8" height="8" rx="2" fill="var(--data-color-1)" />
                        </svg>
                        <span>Week of Sep 21</span>
                    </Text>
                </div>
            </div>
            <svg
                viewBox={`0 0 480 ${height + 28}`}
                className="w-full"
                role="img"
                aria-label="Conversion by funnel step"
            >
                {[0, 25, 50, 75, 100].map((tick) => {
                    const y = height - (tick / 100) * (height - 16) + 0.5
                    return (
                        <g key={tick}>
                            <line x1="40" y1={y} x2="480" y2={y} stroke="var(--color-graph-axis-line)" />
                            <text x="34" y={y + 3} textAnchor="end" fontSize="10" fill="var(--color-graph-axis-label)">
                                {`${tick}%`}
                            </text>
                        </g>
                    )
                })}
                {FUNNEL.map((row, i) => {
                    const x = 64 + i * 106
                    const scale = (height - 16) / 100
                    return (
                        <g key={row.step}>
                            <rect
                                x={x}
                                y={height - row.before * scale}
                                width={28}
                                height={row.before * scale}
                                rx={3}
                                fill="var(--data-color-1)"
                                fillOpacity={0.28}
                            />
                            <rect
                                x={x + 32}
                                y={height - row.after * scale}
                                width={28}
                                height={row.after * scale}
                                rx={3}
                                fill="var(--data-color-1)"
                            />
                            <text
                                x={x + 46}
                                y={height - row.after * scale - 6}
                                textAnchor="middle"
                                fontSize="10"
                                fontWeight="600"
                                fill="currentColor"
                            >
                                {`${row.after}%`}
                            </text>
                            <text
                                x={x + 30}
                                y={height + 18}
                                textAnchor="middle"
                                fontSize="11"
                                fill="var(--color-graph-axis-label)"
                            >
                                {row.step}
                            </text>
                        </g>
                    )
                })}
            </svg>
        </div>
    )
}

function DataDocument(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
                <Heading size="lg" render={<h1 />}>
                    Trial starts by week
                </Heading>
                <Text size="sm" variant="muted">
                    4 rows · 3 columns
                </Text>
            </div>
            <div className="overflow-hidden rounded-lg border border-border">
                <Table fullWidth size="sm">
                    <TableHeader>
                        <TableRow>
                            <TableHead expand>week</TableHead>
                            <TableHead align="right">trial_starts</TableHead>
                            <TableHead align="right">conversion</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {WEEKS.map((row) => (
                            <TableRow key={row.week}>
                                <TableCell className="whitespace-nowrap font-mono">{row.week}</TableCell>
                                <TableCell align="right" className="font-mono tabular-nums">
                                    {row.starts}
                                </TableCell>
                                <TableCell align="right" className="font-mono tabular-nums">
                                    {row.conversion}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
        </div>
    )
}

function ArtifactDocument({ artifact }: { artifact: MockArtifact }): JSX.Element {
    if (artifact.kind === 'chart') {
        return <ChartFigure />
    }
    if (artifact.kind === 'data') {
        return <DataDocument />
    }
    return <ReportDocument />
}

function ArtifactViewer({
    openId,
    onOpen,
    onBack,
}: {
    openId: string
    onOpen: (id: string) => void
    onBack: () => void
}): JSX.Element {
    const index = Math.max(
        0,
        ARTIFACTS.findIndex((artifact) => artifact.id === openId)
    )
    const artifact = ARTIFACTS[index]
    const previous = ARTIFACTS[(index - 1 + ARTIFACTS.length) % ARTIFACTS.length]
    const next = ARTIFACTS[(index + 1) % ARTIFACTS.length]
    return (
        <div className="flex min-h-0 flex-1">
            <aside className="hidden w-64 shrink-0 flex-col gap-2 overflow-y-auto border-r border-border p-3 @min-[52rem]/session:flex">
                <Button variant="default" size="sm" className="self-start" onClick={onBack}>
                    <IconArrowLeft />
                    All artifacts
                </Button>
                <ItemGroup>
                    {ARTIFACTS.map((item) => (
                        <Item
                            key={item.id}
                            size="xs"
                            className={cn('hover:bg-fill-hover', item.id === artifact.id && 'bg-fill-selected')}
                            render={<button type="button" onClick={() => onOpen(item.id)} />}
                        >
                            <ItemMedia variant="icon">
                                <ArtifactIcon kind={item.kind} />
                            </ItemMedia>
                            <ItemContent>
                                <ItemTitle className="truncate">{item.name}</ItemTitle>
                                <ItemDescription>{`${KIND_LABEL[item.kind]} · ${item.size}`}</ItemDescription>
                            </ItemContent>
                        </Item>
                    ))}
                </ItemGroup>
            </aside>
            <div className="flex min-w-0 flex-1 flex-col">
                <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-4 py-2">
                    <div className="@min-[52rem]/session:hidden">
                        <IconAction label="All artifacts" onClick={onBack}>
                            <IconArrowLeft />
                        </IconAction>
                    </div>
                    <ArtifactIcon kind={artifact.kind} className="size-4 text-muted-foreground" />
                    <Text size="sm" className="min-w-0 truncate font-medium">
                        {artifact.name}
                    </Text>
                    <Text size="xs" variant="muted">
                        {`${artifact.size} · ${artifact.updated}`}
                    </Text>
                    <div className="ml-auto flex items-center gap-1">
                        <Text size="xs" variant="muted" className="px-1 tabular-nums">
                            {`${index + 1} of ${ARTIFACTS.length}`}
                        </Text>
                        <IconAction label={`Previous: ${previous.name}`} onClick={() => onOpen(previous.id)}>
                            <IconChevronLeft />
                        </IconAction>
                        <IconAction label={`Next: ${next.name}`} onClick={() => onOpen(next.id)}>
                            <IconChevronRight />
                        </IconAction>
                        <Button variant="outline" size="sm">
                            <IconComment />
                            {artifact.comments === 0
                                ? 'Comment'
                                : artifact.comments === 1
                                  ? '1 comment'
                                  : `${artifact.comments} comments`}
                        </Button>
                        <IconAction label="Download">
                            <IconDownload />
                        </IconAction>
                        <IconAction label="Open in a new tab">
                            <IconExternal />
                        </IconAction>
                    </div>
                </div>
                <div className="@container/viewer flex-1 overflow-y-auto bg-[var(--today-soft)] px-4 py-8 @min-[40rem]/viewer:px-10">
                    <div className="mx-auto w-full max-w-2xl rounded-lg border border-border bg-card px-6 py-8 text-card-foreground shadow-sm @min-[40rem]/viewer:px-12 @min-[40rem]/viewer:py-10">
                        <ArtifactDocument artifact={artifact} />
                    </div>
                </div>
            </div>
        </div>
    )
}

function ArtifactsEmpty({ onBack }: { onBack: () => void }): JSX.Element {
    return (
        <div className="flex flex-1 items-center justify-center px-6 py-10">
            <Empty className="max-w-lg">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconDocument />
                    </EmptyMedia>
                    <EmptyTitle>No artifacts yet</EmptyTitle>
                    <EmptyDescription>
                        Files that the agent writes in this session show here. Ask it for a report, a chart or a CSV.
                    </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button variant="outline" size="sm" onClick={onBack}>
                        Go to the conversation
                    </Button>
                </EmptyContent>
            </Empty>
        </div>
    )
}

function Conversation({
    onOpenArtifact,
    onShowAll,
}: {
    onOpenArtifact: (id: string) => void
    onShowAll: () => void
}): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex-1 overflow-y-auto px-6 py-6">
                <div className="mx-auto flex max-w-3xl flex-col gap-6">
                    <div className="flex justify-end">
                        <ChatBubble variant="muted" align="end" className="max-w-[80%]">
                            <ChatBubbleContent>
                                Trial starts dropped last week. Find the step where people leave and write it up for the
                                team.
                            </ChatBubbleContent>
                        </ChatBubble>
                    </div>
                    <div className="flex flex-col gap-3 text-sm leading-relaxed">
                        <div className="flex flex-col gap-1">
                            <ChatMarker status="done">
                                <ChatMarkerIcon>
                                    <IconDatabase />
                                </ChatMarkerIcon>
                                <ChatMarkerContent>
                                    Ran 4 queries
                                    <ChatMarkerValue>trial funnel</ChatMarkerValue>
                                </ChatMarkerContent>
                            </ChatMarker>
                            <ChatMarker status="done">
                                <ChatMarkerIcon>
                                    <IconSearch />
                                </ChatMarkerIcon>
                                <ChatMarkerContent>Watched 6 session recordings</ChatMarkerContent>
                            </ChatMarker>
                        </div>
                        <p>
                            Trial starts fell 18% week over week. Almost all of the loss is at the plan picker step,
                            which changed in the release on Tuesday. The new layout pushes the start trial button below
                            the fold on laptop screens.
                        </p>
                        <p>I wrote a short report, a chart of each funnel step, and the weekly numbers as a CSV.</p>
                        <div className="flex flex-col gap-2 pt-1">
                            <div className="flex items-center justify-between">
                                <Text size="xs" variant="muted" className="font-medium">
                                    {`${ARTIFACTS.length} artifacts`}
                                </Text>
                                <Button variant="link-muted" size="xs" onClick={onShowAll}>
                                    View all in Artifacts
                                    <IconArrowRight />
                                </Button>
                            </div>
                            <ArtifactRows artifacts={ARTIFACTS} onOpen={onOpenArtifact} size="xs" />
                        </div>
                    </div>
                </div>
            </div>
            <div className="shrink-0 px-6 pb-5 pt-2">
                <div className="mx-auto flex max-w-3xl flex-col gap-3 rounded-xl border border-border bg-card px-4 py-3 shadow-sm">
                    <Text size="sm" variant="muted">
                        Ask a follow-up
                    </Text>
                    <div className="flex justify-end">
                        <IconAction label="Send">
                            <IconArrowRight />
                        </IconAction>
                    </div>
                </div>
            </div>
        </div>
    )
}

function SessionArtifactsMockup({
    initialTab = 'artifacts',
    initialOpenId = null,
    empty = false,
}: {
    initialTab?: SessionTab
    initialOpenId?: string | null
    empty?: boolean
}): JSX.Element {
    const [tab, setTab] = useState<SessionTab>(initialTab)
    const [openId, setOpenId] = useState<string | null>(initialOpenId)
    const openArtifact = (id: string): void => {
        setTab('artifacts')
        setOpenId(id)
    }
    return (
        <WebLayout>
            <div className="@container/session flex min-h-0 flex-1 flex-col">
                <SessionHeader
                    tab={tab}
                    onTabChange={(value) => {
                        setTab(value)
                        setOpenId(null)
                    }}
                    artifactCount={empty ? 0 : ARTIFACTS.length}
                />
                {tab === 'conversation' ? (
                    <Conversation onOpenArtifact={openArtifact} onShowAll={() => setTab('artifacts')} />
                ) : empty ? (
                    <ArtifactsEmpty onBack={() => setTab('conversation')} />
                ) : openId ? (
                    <ArtifactViewer openId={openId} onOpen={setOpenId} onBack={() => setOpenId(null)} />
                ) : (
                    <ArtifactsGallery onOpen={openArtifact} />
                )}
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

export const Gallery: Story = { render: () => <SessionArtifactsMockup /> }

export const ArtifactOpen: Story = { render: () => <SessionArtifactsMockup initialOpenId="a-report" /> }

export const DataArtifactOpen: Story = { render: () => <SessionArtifactsMockup initialOpenId="a-data" /> }

export const ConversationTab: Story = { render: () => <SessionArtifactsMockup initialTab="conversation" /> }

export const NoArtifacts: Story = { render: () => <SessionArtifactsMockup empty /> }
