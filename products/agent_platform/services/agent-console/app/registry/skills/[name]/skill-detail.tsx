'use client'

import { ChevronRightIcon, CopyIcon, FileTextIcon, HistoryIcon, PencilIcon, Trash2Icon } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'

import { Markdown } from '@posthog/agent-chat'

import { FileExplorer, type FileTreeNode } from '@/components/FileExplorer'
import type { SkillTemplateDetail } from '@/lib/registryFixtures'

type ViewMode = 'rendered' | 'raw'
type BodyKey = '__index__'
const INDEX_KEY: BodyKey = '__index__'

export function SkillDetail({ skill }: { skill: SkillTemplateDetail }): React.ReactElement {
    const [selectedPath, setSelectedPath] = useState<string>(INDEX_KEY)
    const [viewMode, setViewMode] = useState<ViewMode>('rendered')

    const tree = buildTree(skill)
    const selected = resolveSelected(skill, selectedPath)

    return (
        <div className="mx-auto max-w-5xl space-y-4 px-6 py-6">
            <Breadcrumb name={skill.name} />
            <SkillHeader skill={skill} />

            <FileExplorer
                storageKey="file-explorer:registry-skill"
                tree={tree}
                selectedPath={selectedPath}
                onSelectPath={setSelectedPath}
                emptyMessage="This skill has no body or companion files."
            >
                <div className="flex h-full flex-col">
                    <header className="flex items-center justify-between gap-2 border-b border-border bg-muted/10 px-3 py-2">
                        <code className="truncate font-mono text-[0.8125rem]">{selected.label}</code>
                        <div className="flex items-center gap-1.5">
                            {selected.isMarkdown ? (
                                <div className="flex overflow-hidden rounded border border-border text-[0.625rem]">
                                    <button
                                        type="button"
                                        onClick={() => setViewMode('rendered')}
                                        aria-pressed={viewMode === 'rendered'}
                                        className={`px-1.5 py-0.5 ${viewMode === 'rendered' ? 'bg-muted font-medium' : 'hover:bg-muted'}`}
                                    >
                                        Rendered
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => setViewMode('raw')}
                                        aria-pressed={viewMode === 'raw'}
                                        className={`border-l border-border px-1.5 py-0.5 ${viewMode === 'raw' ? 'bg-muted font-medium' : 'hover:bg-muted'}`}
                                    >
                                        Raw
                                    </button>
                                </div>
                            ) : null}
                        </div>
                    </header>
                    <div className="min-h-0 flex-1 overflow-auto p-3">
                        {selected.isMarkdown && viewMode === 'rendered' ? (
                            <Markdown>{selected.content}</Markdown>
                        ) : (
                            <pre className="whitespace-pre-wrap break-words font-mono text-[0.75rem] leading-relaxed">
                                {selected.content}
                            </pre>
                        )}
                    </div>
                </div>
            </FileExplorer>

            <UsagesPanel usages={skill.usages} />
            <HistoryPanel history={skill.history} currentVersion={skill.version} />
        </div>
    )
}

function SkillHeader({ skill }: { skill: SkillTemplateDetail }): React.ReactElement {
    const canonical = skill.name.startsWith('@posthog/')
    return (
        <header className="space-y-1.5">
            <div className="flex items-center gap-2">
                <code className="font-mono text-sm">{skill.name}</code>
                <span className="text-[0.6875rem] text-muted-foreground">v{skill.version}</span>
                <Chip tone={canonical ? 'info' : 'muted'}>{canonical ? 'canonical' : 'team'}</Chip>
            </div>
            <p className="text-sm text-foreground/90">{skill.description}</p>
            <div className="flex items-center justify-between pt-1">
                <p className="text-[0.6875rem] text-muted-foreground/80">
                    {skill.created_by ? `by ${skill.created_by}` : 'PostHog-canonical'} · updated{' '}
                    {formatRelative(skill.updated_at)} · {skill.file_count} file{skill.file_count === 1 ? '' : 's'} ·{' '}
                    used by {skill.usage_count} agent{skill.usage_count === 1 ? '' : 's'}
                </p>
                <div className="flex items-center gap-1.5">
                    <ActionButton icon={<PencilIcon className="h-3 w-3" />} label="Edit" disabled />
                    <ActionButton icon={<CopyIcon className="h-3 w-3" />} label="Duplicate" disabled />
                    <ActionButton
                        icon={<Trash2Icon className="h-3 w-3" />}
                        label="Archive"
                        disabled
                        tone="destructive"
                    />
                </div>
            </div>
            <p className="text-[0.6875rem] italic text-muted-foreground/70">
                Edit / duplicate / archive land with the backend — v0 is read-only against fixtures.
            </p>
        </header>
    )
}

function ActionButton({
    icon,
    label,
    disabled,
    tone = 'default',
}: {
    icon: React.ReactNode
    label: string
    disabled?: boolean
    tone?: 'default' | 'destructive'
}): React.ReactElement {
    return (
        <button
            type="button"
            disabled={disabled}
            className={
                'inline-flex h-6 cursor-pointer items-center gap-1 rounded border px-2 text-[0.6875rem] transition-colors disabled:cursor-not-allowed disabled:opacity-50 ' +
                (tone === 'destructive'
                    ? 'border-destructive-foreground/40 text-destructive-foreground hover:bg-destructive/10'
                    : 'border-border bg-card hover:bg-accent')
            }
        >
            {icon}
            {label}
        </button>
    )
}

function UsagesPanel({ usages }: { usages: SkillTemplateDetail['usages'] }): React.ReactElement {
    return (
        <section className="overflow-hidden rounded-md border border-border bg-card">
            <header className="flex items-center justify-between gap-2 border-b border-border bg-muted/30 px-3 py-2">
                <h3 className="text-[0.6875rem] font-medium uppercase tracking-wide text-muted-foreground">Used by</h3>
                <span className="text-[0.625rem] text-muted-foreground/80">
                    {usages.length} agent{usages.length === 1 ? '' : 's'}
                </span>
            </header>
            {usages.length === 0 ? (
                <div className="px-3 py-3 text-xs text-muted-foreground">No agents pin this skill yet.</div>
            ) : (
                <ul className="divide-y divide-border">
                    {usages.map((u) => (
                        <li
                            key={`${u.agent_slug}:${u.revision_short_id}`}
                            className="flex items-center justify-between px-3 py-2 text-xs"
                        >
                            <Link href={`/agents/${u.agent_slug}`} className="flex items-center gap-2 hover:underline">
                                <span className="font-medium">{u.agent_name}</span>
                                <code className="text-[0.6875rem] text-muted-foreground">{u.revision_short_id}</code>
                            </Link>
                            <span className="text-[0.6875rem] text-muted-foreground">pinned v{u.pinned_version}</span>
                        </li>
                    ))}
                </ul>
            )}
        </section>
    )
}

function HistoryPanel({
    history,
    currentVersion,
}: {
    history: SkillTemplateDetail['history']
    currentVersion: number
}): React.ReactElement {
    if (history.length === 0) {
        return <></>
    }
    return (
        <section className="overflow-hidden rounded-md border border-border bg-card">
            <header className="flex items-center gap-2 border-b border-border bg-muted/30 px-3 py-2">
                <HistoryIcon className="h-3 w-3 text-muted-foreground" />
                <h3 className="text-[0.6875rem] font-medium uppercase tracking-wide text-muted-foreground">
                    Version history
                </h3>
            </header>
            <ul className="divide-y divide-border">
                <li className="flex items-center justify-between px-3 py-2 text-xs">
                    <span className="font-medium">v{currentVersion}</span>
                    <span className="text-[0.6875rem] text-muted-foreground">current</span>
                </li>
                {history.map((h) => (
                    <li key={h.version} className="flex items-center justify-between px-3 py-2 text-xs">
                        <span>
                            <span className="font-medium">v{h.version}</span>
                            {h.note ? <span className="text-muted-foreground"> · {h.note}</span> : null}
                        </span>
                        <span className="text-[0.6875rem] text-muted-foreground">
                            {formatRelative(h.updated_at)}
                            {h.created_by ? ` · ${h.created_by}` : ''}
                        </span>
                    </li>
                ))}
            </ul>
        </section>
    )
}

function Chip({ tone, children }: { tone: 'muted' | 'info'; children: React.ReactNode }): React.ReactElement {
    const cls =
        tone === 'info'
            ? 'border-info-foreground/30 bg-info/30 text-info-foreground'
            : 'border-border bg-muted/40 text-muted-foreground'
    return (
        <span
            className={`inline-flex h-4 items-center rounded-full border px-1.5 text-[0.625rem] uppercase tracking-wide ${cls}`}
        >
            {children}
        </span>
    )
}

function Breadcrumb({ name }: { name: string }): React.ReactElement {
    return (
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Link href="/registry" className="cursor-pointer hover:text-foreground">
                Tools &amp; skills
            </Link>
            <ChevronRightIcon className="h-3 w-3" />
            <Link href="/registry" className="cursor-pointer hover:text-foreground">
                Skills
            </Link>
            <ChevronRightIcon className="h-3 w-3" />
            <code className="text-foreground">{name}</code>
        </div>
    )
}

/* ── Tree + selection helpers ───────────────────────────────────── */

function buildTree(skill: SkillTemplateDetail): FileTreeNode {
    const root: FileTreeNode = { type: 'folder', name: '', children: [] }
    // Index body is a virtual "SKILL.md" file at the top.
    root.children!.push({
        type: 'file',
        name: 'SKILL.md',
        path: INDEX_KEY,
        icon: <FileTextIcon className="h-3.5 w-3.5" />,
    })
    for (const file of skill.files) {
        addFile(root, file.path)
    }
    return root
}

function addFile(root: FileTreeNode, fullPath: string): void {
    const parts = fullPath.split('/')
    let cursor: FileTreeNode = root
    for (let i = 0; i < parts.length - 1; i++) {
        cursor.children ??= []
        const name = parts[i]
        let child = cursor.children.find((c) => c.type === 'folder' && c.name === name)
        if (!child) {
            child = { type: 'folder', name, children: [] }
            cursor.children.push(child)
        }
        cursor = child
    }
    cursor.children ??= []
    cursor.children.push({
        type: 'file',
        name: parts[parts.length - 1],
        path: fullPath,
        icon: <FileTextIcon className="h-3.5 w-3.5" />,
    })
}

function resolveSelected(
    skill: SkillTemplateDetail,
    path: string
): { label: string; content: string; isMarkdown: boolean } {
    if (path === INDEX_KEY) {
        return { label: 'SKILL.md', content: skill.body, isMarkdown: true }
    }
    const file = skill.files.find((f) => f.path === path)
    if (!file) {
        return { label: path, content: '(file not found)', isMarkdown: false }
    }
    return { label: file.path, content: file.content, isMarkdown: file.path.endsWith('.md') }
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
