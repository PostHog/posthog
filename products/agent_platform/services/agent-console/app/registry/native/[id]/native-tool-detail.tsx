'use client'

import { ChevronRightIcon } from 'lucide-react'
import Link from 'next/link'

import { JsonView } from '@posthog/agent-chat'

import type { NativeToolCatalogEntry } from '@/lib/apiClient'

export function NativeToolDetail({ tool }: { tool: NativeToolCatalogEntry }): React.ReactElement {
    const { schema } = tool
    return (
        <div className="mx-auto max-w-5xl space-y-4 px-6 py-6">
            <Breadcrumb name={tool.id} />
            <header className="space-y-1.5">
                <div className="flex items-center gap-2">
                    <code className="font-mono text-sm">{tool.id}</code>
                    <Chip tone="info">native</Chip>
                    <Chip tone="muted">{schema.cost_hint}</Chip>
                </div>
                <p className="text-sm text-foreground/90">{schema.description}</p>
                <p className="text-[0.6875rem] text-muted-foreground/80">
                    Native tools ship with the agent runner — read-only. Source lives at{' '}
                    <code className="text-[0.6875rem]">services/agent-tools/src/</code>.
                </p>
            </header>

            {schema.requires.integrations.length > 0 || schema.requires.scopes.length > 0 ? (
                <Section title="Requires">
                    <div className="flex flex-wrap gap-1.5 text-xs">
                        {schema.requires.integrations.map((i) => (
                            <Chip key={`int:${i}`} tone="muted">
                                integration: {i}
                            </Chip>
                        ))}
                        {schema.requires.scopes.map((s) => (
                            <Chip key={`scope:${s}`} tone="muted">
                                scope: {s}
                            </Chip>
                        ))}
                    </div>
                </Section>
            ) : null}

            <Section title="Arguments">
                <div className="rounded-md border border-border bg-muted/20 p-3">
                    <JsonView value={schema.args} expandToLevel={2} />
                </div>
            </Section>

            <Section title="Returns">
                <div className="rounded-md border border-border bg-muted/20 p-3">
                    <JsonView value={schema.returns} expandToLevel={1} />
                </div>
            </Section>
        </div>
    )
}

function Section({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement {
    return (
        <section className="space-y-2">
            <h2 className="text-[0.6875rem] font-medium uppercase tracking-wide text-muted-foreground">{title}</h2>
            {children}
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
                Native tools
            </Link>
            <ChevronRightIcon className="h-3 w-3" />
            <code className="text-foreground">{name}</code>
        </div>
    )
}
