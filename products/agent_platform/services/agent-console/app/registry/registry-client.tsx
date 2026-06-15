'use client'

import { LibraryIcon, PuzzleIcon, SearchIcon, ServerIcon, WrenchIcon } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { useSessionTeamId } from '@/components/session-context'
import { listNativeTools, type NativeToolCatalogEntry } from '@/lib/apiClient'
import type {
    CustomToolTemplateSummaryApi as CustomToolTemplateSummary,
    SkillTemplateSummaryApi as SkillTemplateSummary,
} from '@/lib/registryApiTypes'
import { listCustomToolTemplates, listSkillTemplates } from '@/lib/registryClient'
import { useResource } from '@/lib/useResource'

type TabKey = 'native' | 'skills' | 'tools'

export function RegistryClient(): React.ReactElement {
    const [tab, setTab] = useState<TabKey>('native')
    const [query, setQuery] = useState('')

    return (
        <div className="mx-auto max-w-5xl px-6 py-6">
            <header className="space-y-1">
                <div className="flex items-center gap-2">
                    <LibraryIcon className="h-4 w-4 text-muted-foreground" />
                    <h1 className="text-xl font-medium tracking-tight">Tools &amp; skills</h1>
                </div>
                <p className="text-sm text-muted-foreground">
                    The catalog of capabilities every agent can pull from. Native tools ship with the runner. Skills and
                    custom tools are team-owned and versioned — agents pin a specific version into their bundle at
                    freeze time.
                </p>
            </header>

            <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)} className="mt-5">
                <div className="flex items-center justify-between gap-3 border-b border-border">
                    <TabsList variant="line">
                        <TabsTrigger value="native">Native tools</TabsTrigger>
                        <TabsTrigger value="skills">Skills</TabsTrigger>
                        <TabsTrigger value="tools">Custom tools</TabsTrigger>
                    </TabsList>
                    <div className="relative mb-1.5 w-64 max-w-[40%]">
                        <SearchIcon className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
                        <input
                            type="search"
                            value={query}
                            onChange={(e) => setQuery(e.currentTarget.value)}
                            placeholder="Search name or description…"
                            className="h-7 w-full rounded border border-input bg-background pl-7 pr-2 text-xs"
                        />
                    </div>
                </div>

                <TabsContent value="native" className="mt-4">
                    <NativeToolsList query={query} />
                </TabsContent>

                <TabsContent value="skills" className="mt-4">
                    <SkillsList query={query} />
                </TabsContent>

                <TabsContent value="tools" className="mt-4">
                    <CustomToolsList query={query} />
                </TabsContent>
            </Tabs>
        </div>
    )
}

/* ── Native tools tab (live) ────────────────────────────────────── */

function NativeToolsList({ query }: { query: string }): React.ReactElement {
    const teamId = useSessionTeamId()!
    const res = useResource(() => listNativeTools(teamId).catch(() => [] as NativeToolCatalogEntry[]), [teamId])
    if (res.loading && !res.data) {
        return <EmptyState>Loading native tool catalog…</EmptyState>
    }
    const tools = res.data ?? []
    const filtered = filterByQuery(tools, query, (t) => [t.id, t.schema.description])
    if (filtered.length === 0) {
        return <EmptyState>No tools match.</EmptyState>
    }
    return (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {filtered.map((t) => (
                <li key={t.id}>
                    <Card
                        href={`/registry/native/${encodeURIComponent(t.id)}`}
                        icon={<ServerIcon className="h-3.5 w-3.5" />}
                        kindLabel="native"
                        kindTone="info"
                        title={<code className="font-mono text-[0.8125rem]">{t.id}</code>}
                        description={t.schema.description}
                        meta={
                            <>
                                <Meta label="cost">{t.schema.cost_hint}</Meta>
                                {t.schema.requires.integrations.length > 0 ? (
                                    <Meta label="needs">{t.schema.requires.integrations.join(', ')}</Meta>
                                ) : null}
                            </>
                        }
                    />
                </li>
            ))}
        </ul>
    )
}

/* ── Skills tab (live) ──────────────────────────────────────────── */

function SkillsList({ query }: { query: string }): React.ReactElement {
    const teamId = useSessionTeamId()!
    const res = useResource(() => listSkillTemplates(teamId).catch(() => [] as SkillTemplateSummary[]), [teamId])
    if (res.loading && !res.data) {
        return <EmptyState>Loading skill templates…</EmptyState>
    }
    const skills = res.data ?? []
    const filtered = filterByQuery<SkillTemplateSummary>(skills, query, (s) => [s.name, s.description ?? ''])
    if (filtered.length === 0) {
        return <EmptyState>No skills match.</EmptyState>
    }
    return (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {filtered.map((s) => (
                <li key={s.id}>
                    <Card
                        href={`/registry/skills/${encodeURIComponent(s.name)}`}
                        icon={<PuzzleIcon className="h-3.5 w-3.5" />}
                        kindLabel={isCanonical(s.name) ? 'canonical' : 'team'}
                        kindTone={isCanonical(s.name) ? 'info' : 'muted'}
                        title={
                            <span className="flex items-baseline gap-2">
                                <code className="font-mono text-[0.8125rem]">{s.name}</code>
                                <span className="text-[0.6875rem] text-muted-foreground">v{s.version}</span>
                            </span>
                        }
                        description={s.description ?? ''}
                        meta={
                            <>
                                <Meta label="files">{String(s.file_count)}</Meta>
                                <Meta label="used by">{`${s.usage_count} agent${s.usage_count === 1 ? '' : 's'}`}</Meta>
                                <Meta label="updated">{formatRelative(s.updated_at)}</Meta>
                            </>
                        }
                    />
                </li>
            ))}
        </ul>
    )
}

/* ── Custom tools tab (live) ────────────────────────────────────── */

function CustomToolsList({ query }: { query: string }): React.ReactElement {
    const teamId = useSessionTeamId()!
    const res = useResource(
        () => listCustomToolTemplates(teamId).catch(() => [] as CustomToolTemplateSummary[]),
        [teamId]
    )
    if (res.loading && !res.data) {
        return <EmptyState>Loading custom tool templates…</EmptyState>
    }
    const tools = res.data ?? []
    const filtered = filterByQuery<CustomToolTemplateSummary>(tools, query, (t) => [t.name, t.description ?? ''])
    if (filtered.length === 0) {
        return <EmptyState>No custom tools match.</EmptyState>
    }
    return (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {filtered.map((t) => (
                <li key={t.id}>
                    <Card
                        href={`/registry/tools/${encodeURIComponent(t.name)}`}
                        icon={<WrenchIcon className="h-3.5 w-3.5" />}
                        kindLabel={isCanonical(t.name) ? 'canonical' : 'team'}
                        kindTone={isCanonical(t.name) ? 'info' : 'muted'}
                        title={
                            <span className="flex items-baseline gap-2">
                                <code className="font-mono text-[0.8125rem]">{t.name}</code>
                                <span className="text-[0.6875rem] text-muted-foreground">v{t.version}</span>
                            </span>
                        }
                        description={t.description ?? ''}
                        meta={
                            <>
                                {(t.requires_secrets ?? []).length > 0 ? (
                                    <Meta label="needs">{(t.requires_secrets ?? []).join(', ')}</Meta>
                                ) : null}
                                <Meta label="used by">{`${t.usage_count} agent${t.usage_count === 1 ? '' : 's'}`}</Meta>
                                <Meta label="updated">{formatRelative(t.updated_at)}</Meta>
                            </>
                        }
                    />
                </li>
            ))}
        </ul>
    )
}

/* ── Shared bits ────────────────────────────────────────────────── */

function Card({
    href,
    icon,
    kindLabel,
    kindTone,
    title,
    description,
    meta,
}: {
    href: string
    icon: React.ReactNode
    kindLabel: string
    kindTone: 'info' | 'muted'
    title: React.ReactNode
    description: string
    meta?: React.ReactNode
}): React.ReactElement {
    return (
        <Link
            href={href}
            className="flex h-full flex-col gap-2 rounded-md border border-border bg-card p-3 transition-colors hover:bg-accent/40"
        >
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-muted-foreground">{icon}</div>
                <span
                    className={
                        'inline-flex h-4 items-center rounded-full border px-1.5 text-[0.625rem] uppercase tracking-wide ' +
                        (kindTone === 'info'
                            ? 'border-info-foreground/30 bg-info/30 text-info-foreground'
                            : 'border-border bg-muted/40 text-muted-foreground')
                    }
                >
                    {kindLabel}
                </span>
            </div>
            <div>{title}</div>
            <p className="line-clamp-3 text-xs text-muted-foreground">{description}</p>
            {meta ? (
                <div className="mt-auto flex flex-wrap gap-x-3 gap-y-0.5 text-[0.6875rem] text-muted-foreground/80">
                    {meta}
                </div>
            ) : null}
        </Link>
    )
}

function Meta({ label, children }: { label: string; children: React.ReactNode }): React.ReactElement {
    return (
        <span className="inline-flex items-baseline gap-1">
            <span className="uppercase tracking-wide">{label}</span>
            <span className="text-foreground/80">{children}</span>
        </span>
    )
}

function EmptyState({ children }: { children: React.ReactNode }): React.ReactElement {
    return (
        <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
            {children}
        </div>
    )
}

function isCanonical(name: string): boolean {
    return name.startsWith('@posthog/')
}

function filterByQuery<T>(items: T[], query: string, fields: (item: T) => string[]): T[] {
    const q = query.trim().toLowerCase()
    if (!q) {
        return items
    }
    return items.filter((item) =>
        fields(item)
            .filter(Boolean)
            .some((s) => s.toLowerCase().includes(q))
    )
}

function formatRelative(iso: string): string {
    const ts = new Date(iso).getTime()
    if (!ts) {
        return '—'
    }
    const diff = Math.max(0, Date.now() - ts)
    const day = 24 * 60 * 60 * 1000
    if (diff < day) {
        return 'today'
    }
    const days = Math.floor(diff / day)
    if (days < 30) {
        return `${days}d ago`
    }
    const months = Math.floor(days / 30)
    return `${months}mo ago`
}
