/**
 * `<JsonView />` — a tree-style JSON renderer with a raw fallback.
 *
 * Two views, one toggle:
 *  - **tree** (default): collapsible objects + arrays, value-type
 *    accents (numbers blue, booleans italic, nulls muted), copyable
 *    key paths in a glance.
 *  - **raw**: the same value as a JSON.stringify(_, _, 2) `<pre>` —
 *    no surprises, copy-pastes cleanly into other tools.
 *
 * The toggle lives top-right of the wrapper and is always visible
 * (low-contrast by default; brightens on hover) so users can find it
 * without first hovering the JSON.
 *
 * Used everywhere we used to render `<pre>{JSON.stringify(...)}</pre>`
 * — tool call args/results, approval args, bundle file content for
 * `.json` files, etc.
 */

import { ChevronDownIcon, ChevronRightIcon } from 'lucide-react'
import { useState } from 'react'
import { stringify as yamlStringify } from 'yaml'

export type JsonViewMode = 'tree' | 'json' | 'yaml'

const VIEW_MODES: JsonViewMode[] = ['tree', 'json', 'yaml']

export interface JsonViewProps {
    value: unknown
    /** Initial view. Defaults to 'tree'. */
    defaultView?: JsonViewMode
    /** Auto-expand objects/arrays up to (but not including) this nesting depth. Default 2. */
    expandToLevel?: number
    className?: string
}

export function JsonView({ value, defaultView = 'tree', expandToLevel = 2, className }: JsonViewProps): React.ReactElement {
    const [view, setView] = useState<JsonViewMode>(defaultView)

    return (
        <div
            className={
                'relative rounded-md border border-border/60 bg-background/60 text-[0.75rem] leading-snug' +
                (className ? ` ${className}` : '')
            }
            data-slot="json-view"
        >
            <div className="absolute right-1 top-1 z-10">
                <ViewToggle view={view} onChange={setView} />
            </div>
            <div className="overflow-x-auto px-2.5 py-2 pr-[140px] font-mono">
                {view === 'tree' ? (
                    <TreeNode value={value} level={0} expandToLevel={expandToLevel} />
                ) : (
                    <pre className="whitespace-pre-wrap break-words">{serialize(value, view)}</pre>
                )}
            </div>
        </div>
    )
}

function ViewToggle({ view, onChange }: { view: JsonViewMode; onChange: (next: JsonViewMode) => void }): React.ReactElement {
    return (
        <div
            className="inline-flex overflow-hidden rounded border border-border/60 bg-background/80 shadow-sm"
            role="group"
            aria-label="View format"
        >
            {VIEW_MODES.map((m, i) => (
                <button
                    key={m}
                    type="button"
                    onClick={() => onChange(m)}
                    aria-pressed={view === m}
                    className={
                        (view === m
                            ? 'bg-accent text-foreground'
                            : 'text-muted-foreground/80 hover:bg-accent/50 hover:text-foreground') +
                        ' cursor-pointer px-1.5 py-0.5 text-[0.625rem] font-medium uppercase tracking-wide transition-colors' +
                        (i > 0 ? ' border-l border-border/60' : '')
                    }
                >
                    {m}
                </button>
            ))}
        </div>
    )
}

function serialize(value: unknown, mode: 'json' | 'yaml'): string {
    if (mode === 'json') {
        try {
            return JSON.stringify(value, null, 2)
        } catch {
            return String(value)
        }
    }
    try {
        // `yaml` package's defaults produce reasonable output:
        //  - 2-space indent
        //  - block-style for nested structures
        //  - quoted strings only when ambiguous
        return yamlStringify(value, { indent: 2, lineWidth: 100 })
    } catch {
        return String(value)
    }
}

function TreeNode({
    value,
    level,
    expandToLevel,
}: {
    value: unknown
    level: number
    expandToLevel: number
}): React.ReactElement {
    if (value === null) {
        return <span className="italic text-muted-foreground">null</span>
    }
    if (value === undefined) {
        return <span className="italic text-muted-foreground">undefined</span>
    }
    const t = typeof value
    if (t === 'string') {
        return <StringValue text={value as string} />
    }
    if (t === 'number' || t === 'bigint') {
        return <span className="text-info">{String(value)}</span>
    }
    if (t === 'boolean') {
        return <span className="italic text-info">{String(value)}</span>
    }
    if (Array.isArray(value)) {
        return <ArrayValue arr={value} level={level} expandToLevel={expandToLevel} />
    }
    if (t === 'object') {
        return <ObjectValue obj={value as Record<string, unknown>} level={level} expandToLevel={expandToLevel} />
    }
    return <span className="text-muted-foreground">{String(value)}</span>
}

function StringValue({ text }: { text: string }): React.ReactElement {
    return (
        <span>
            <span className="text-muted-foreground">&quot;</span>
            <span className="whitespace-pre-wrap break-words">{text}</span>
            <span className="text-muted-foreground">&quot;</span>
        </span>
    )
}

function ObjectValue({
    obj,
    level,
    expandToLevel,
}: {
    obj: Record<string, unknown>
    level: number
    expandToLevel: number
}): React.ReactElement {
    const keys = Object.keys(obj)
    const [expanded, setExpanded] = useState(level < expandToLevel)

    if (keys.length === 0) {
        return <span className="text-muted-foreground">{'{ }'}</span>
    }

    if (!expanded) {
        return (
            <button
                type="button"
                onClick={() => setExpanded(true)}
                className="inline-flex cursor-pointer items-center gap-0.5 rounded px-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                aria-label={`Expand object (${keys.length} keys)`}
            >
                <ChevronRightIcon className="h-3 w-3" />
                <span>{`{ ${keys.length} ${keys.length === 1 ? 'key' : 'keys'} }`}</span>
            </button>
        )
    }

    return (
        <span className="inline-block w-full align-top">
            <button
                type="button"
                onClick={() => setExpanded(false)}
                className="inline-flex cursor-pointer items-center gap-0.5 rounded px-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                aria-label="Collapse"
            >
                <ChevronDownIcon className="h-3 w-3" />
                <span>{'{'}</span>
            </button>
            <div className="ml-3 border-l border-border/40 pl-2">
                {keys.map((k) => (
                    <KeyValueRow key={k} k={k} v={obj[k]} level={level + 1} expandToLevel={expandToLevel} />
                ))}
            </div>
            <span className="text-muted-foreground">{'}'}</span>
        </span>
    )
}

function ArrayValue({
    arr,
    level,
    expandToLevel,
}: {
    arr: unknown[]
    level: number
    expandToLevel: number
}): React.ReactElement {
    const [expanded, setExpanded] = useState(level < expandToLevel)

    if (arr.length === 0) {
        return <span className="text-muted-foreground">[ ]</span>
    }

    if (!expanded) {
        return (
            <button
                type="button"
                onClick={() => setExpanded(true)}
                className="inline-flex cursor-pointer items-center gap-0.5 rounded px-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                aria-label={`Expand array (${arr.length} items)`}
            >
                <ChevronRightIcon className="h-3 w-3" />
                <span>{`[ ${arr.length} ${arr.length === 1 ? 'item' : 'items'} ]`}</span>
            </button>
        )
    }

    return (
        <span className="inline-block w-full align-top">
            <button
                type="button"
                onClick={() => setExpanded(false)}
                className="inline-flex cursor-pointer items-center gap-0.5 rounded px-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                aria-label="Collapse"
            >
                <ChevronDownIcon className="h-3 w-3" />
                <span>{'['}</span>
            </button>
            <div className="ml-3 border-l border-border/40 pl-2">
                {arr.map((item, i) => (
                    <div key={i} className="flex gap-2">
                        <span className="select-none text-muted-foreground/60">{i}</span>
                        <span className="min-w-0 flex-1">
                            <TreeNode value={item} level={level + 1} expandToLevel={expandToLevel} />
                        </span>
                    </div>
                ))}
            </div>
            <span className="text-muted-foreground">{']'}</span>
        </span>
    )
}

function KeyValueRow({
    k,
    v,
    level,
    expandToLevel,
}: {
    k: string
    v: unknown
    level: number
    expandToLevel: number
}): React.ReactElement {
    return (
        <div className="flex gap-1.5">
            <span className="shrink-0 text-muted-foreground">
                <span className="text-muted-foreground/60">&quot;</span>
                <span className="text-foreground">{k}</span>
                <span className="text-muted-foreground/60">&quot;</span>
                <span>:</span>
            </span>
            <span className="min-w-0 flex-1">
                <TreeNode value={v} level={level} expandToLevel={expandToLevel} />
            </span>
        </div>
    )
}
