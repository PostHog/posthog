// KeaDevtools.tsx
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { getContext } from 'kea'
import type { BuiltLogic, Context as KeaContext } from 'kea'

type MountedMap = Record<string, BuiltLogic>
type SortMode = 'alpha' | 'recent'
type Tab = 'logics' | 'actions'

type KeaDevtoolsProps = {
    defaultOpen?: boolean
    buttonSize?: number
    offset?: number
    zIndex?: number
    maxActions?: number
}

type ActionLogItem = { id: number; ts: number; type: string; payload: unknown }

function useStoreTick(): number {
    const { store } = getContext() as KeaContext
    const [tick, setTick] = useState(0)
    useEffect(() => {
        const unsub = store.subscribe(() => Promise.resolve().then(() => setTick((t) => (t + 1) % 1_000_000_000)))
        return unsub
    }, [store])
    return tick
}

function compactJSON(x: unknown) {
    try {
        return JSON.stringify(x)
    } catch {
        return String(x)
    }
}

/* ---------- naming ---------- */

function displayName(logic: BuiltLogic): string {
    const parts = logic.pathString.split('.')
    const hasKey = typeof logic.key !== 'undefined'

    if (hasKey && parts.length >= 2) {
        const keyStr = String(logic.key)
        const keyIndex = parts.lastIndexOf(keyStr)
        if (keyIndex > 0) {
            const name = parts[keyIndex - 1]
            return `${name}.${keyStr}`
        }
    }

    return parts[parts.length - 1]
}

/** size metric → used for a subtle tint */
function logicSize(logic: BuiltLogic): number {
    const c = Math.max(0, Object.keys(logic.connections || {}).length - 1)
    const a = Object.keys(logic.actions || {}).length
    const s = Object.keys(logic.selectors || {}).length
    const v = Object.keys(logic.values || {}).length
    return c + a + s + v
}

/* ---------- small UI atoms ---------- */

function Section({
    title,
    count,
    children,
}: React.PropsWithChildren<{ title: string; count?: number }>): JSX.Element | null {
    if (!children) {
        return null
    }
    return (
        <div style={{ marginTop: 10 }}>
            <strong>
                {title}
                {typeof count === 'number' ? ` (${count})` : ''}
            </strong>
            <div>{children}</div>
        </div>
    )
}

const linkChip: React.CSSProperties = {
    border: '1px solid rgba(0,0,0,0.12)',
    background: '#fff',
    padding: '4px 8px',
    borderRadius: 999,
    cursor: 'pointer',
    fontSize: 12,
}

/* ---------- right side: sections ---------- */

function Connections({ logic, onOpen }: { logic: BuiltLogic; onOpen: (path: string) => void }): JSX.Element | null {
    const keys = Object.keys(logic.connections || {})
        .filter((k) => k !== logic.pathString)
        .sort((a, b) => a.localeCompare(b))
    if (!keys.length) {
        return null
    }
    return (
        <Section title="Connections" count={keys.length}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {keys.map((k) => (
                    <button key={k} type="button" onClick={() => onOpen(k)} style={linkChip}>
                        {k}
                    </button>
                ))}
            </div>
        </Section>
    )
}

function ReverseConnections({
    logic,
    mounted,
    onOpen,
}: {
    logic: BuiltLogic
    mounted: MountedMap
    onOpen: (path: string) => void
}): JSX.Element | null {
    const me = logic.pathString
    const incoming = useMemo(() => {
        return Object.keys(mounted)
            .filter((k) => mounted[k]?.connections && mounted[k].connections[me] && k !== me)
            .sort((a, b) => a.localeCompare(b))
    }, [mounted, me])

    if (!incoming.length) {
        return null
    }
    return (
        <Section title="Reverse connections" count={incoming.length}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {incoming.map((k) => (
                    <button key={k} type="button" onClick={() => onOpen(k)} style={linkChip}>
                        {k}
                    </button>
                ))}
            </div>
        </Section>
    )
}

function ActionsList({ logic }: { logic: BuiltLogic }): JSX.Element | null {
    const keys = Object.keys(logic.actions || {}).sort((a, b) => a.localeCompare(b))
    if (!keys.length) {
        return null
    }

    const run = async (name: string): void => {
        try {
            const raw = window.prompt(`Args for ${name} (JSON array)`, '[]')
            if (raw === null) {
                return
            }
            const args = raw.trim() === '' ? [] : (JSON.parse(raw) as any[])
            const fn = (logic.actions as Record<string, (...a: any[]) => void>)[name]
            fn(...args)
        } catch (e: any) {
            window.alert(`Failed to dispatch: ${e?.message ?? e}`)
        }
    }

    return (
        <Section title="Actions" count={keys.length}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 6 }}>
                {keys.map((k) => (
                    <button
                        key={k}
                        type="button"
                        onClick={() => run(k)}
                        title="Click to run (will prompt for args)"
                        style={pill}
                    >
                        ▶︎ {k}
                    </button>
                ))}
            </div>
        </Section>
    )
}

function Values({ logic }: { logic: BuiltLogic }): JSX.Element | null {
    useStoreTick() // keep fresh
    const keys = useMemo(() => Object.keys(logic.values || {}).sort((a, b) => a.localeCompare(b)), [logic.values])
    if (!keys.length) {
        return null
    }

    return (
        <Section title="Values" count={keys.length}>
            <div
                style={{
                    display: 'grid',
                    gridTemplateColumns: 'max-content 1fr',
                    columnGap: 12,
                    rowGap: 6,
                    alignItems: 'center',
                }}
            >
                {keys.map((k) => (
                    <React.Fragment key={k}>
                        <div style={{ fontWeight: 500, whiteSpace: 'nowrap' }}>{k}</div>
                        <textarea
                            readOnly
                            rows={1}
                            value={compactJSON((logic.values as Record<string, unknown>)[k])}
                            style={{
                                width: '100%',
                                height: 28, // single line; user can resize
                                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                                resize: 'vertical',
                                border: '1px solid rgba(0,0,0,0.12)',
                                borderRadius: 6,
                                padding: '4px 6px',
                            }}
                        />
                    </React.Fragment>
                ))}
            </div>
        </Section>
    )
}

/* ---------- main component ---------- */

export default function KeaDevtools({
    defaultOpen = false,
    buttonSize = 56,
    offset = 16,
    zIndex = 2147483000,
    maxActions = 1000,
}: KeaDevtoolsProps): JSX.Element {
    const [open, setOpen] = useState(defaultOpen)
    const [activeTab, setActiveTab] = useState<Tab>('logics')
    const [selectedKey, setSelectedKey] = useState<string | null>(null)
    const [sortMode, setSortMode] = useState<SortMode>('alpha')
    const [query, setQuery] = useState('')
    const recent = useRef<Map<string, number>>(new Map())
    const actionId = useRef(1)
    const [actions, setActions] = useState<ActionLogItem[]>([])
    const [paused, setPaused] = useState(false)
    const dispatchPatched = useRef(false)

    const { mount, store } = getContext() as KeaContext
    const mounted = (mount?.mounted ?? {}) as MountedMap

    // collect actions
    useEffect(() => {
        if (dispatchPatched.current) {
            return
        }
        const s: any = store as any
        const originalDispatch = s.dispatch
        s.__keaDevtoolsOriginalDispatch = originalDispatch
        s.dispatch = (action: any) => {
            if (!paused) {
                const entry: ActionLogItem = {
                    id: actionId.current++,
                    ts: Date.now(),
                    type: String(action?.type ?? 'UNKNOWN'),
                    payload: action?.payload,
                }
                setActions((prev) => {
                    const next = [...prev, entry]
                    if (next.length > maxActions) {
                        next.splice(0, next.length - maxActions)
                    }
                    return next
                })
            }
            return originalDispatch(action)
        }
        dispatchPatched.current = true
        return () => {
            if (s.__keaDevtoolsOriginalDispatch) {
                s.dispatch = s.__keaDevtoolsOriginalDispatch
            }
        }
    }, [store, paused, maxActions])

    // keys + default selection (sort using displayName with `key` rule)
    const allKeys = useMemo(
        () => Object.keys(mounted).sort((a, b) => displayName(mounted[a]).localeCompare(displayName(mounted[b]))),
        [mounted]
    )

    useEffect(() => {
        if (!selectedKey && allKeys.length) {
            setSelectedKey(allKeys[0])
            recent.current.set(allKeys[0], Date.now())
        }
    }, [selectedKey, allKeys])

    // left list: filter + sort
    const visibleKeys = useMemo(() => {
        const q = query.trim().toLowerCase()
        const base = q
            ? allKeys.filter((k) => {
                  const name = displayName(mounted[k]).toLowerCase()
                  return name.includes(q) || k.toLowerCase().includes(q)
              })
            : allKeys.slice()
        if (sortMode === 'recent') {
            base.sort((a, b) => (recent.current.get(b) ?? 0) - (recent.current.get(a) ?? 0))
        }
        return base
    }, [allKeys, sortMode, query, mounted])

    const selectedLogic = selectedKey ? mounted[selectedKey] : undefined

    const header = (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px' }}>
            <div style={{ fontWeight: 800, fontSize: 16 }}>Kea Devtools</div>
            {activeTab === 'logics' ? (
                <div style={{ color: 'rgba(0,0,0,0.55)' }}>{allKeys.length} mounted</div>
            ) : (
                <div style={{ color: 'rgba(0,0,0,0.55)' }}>{actions.length} actions</div>
            )}
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                <button
                    type="button"
                    onClick={() => setActiveTab('logics')}
                    style={tabBtnStyle(activeTab === 'logics')}
                >
                    Logics
                </button>
                <button
                    type="button"
                    onClick={() => setActiveTab('actions')}
                    style={tabBtnStyle(activeTab === 'actions')}
                >
                    Actions
                </button>
                <button type="button" onClick={() => setOpen(false)} style={simpleBtnStyle}>
                    Close
                </button>
            </div>
        </div>
    )

    return (
        <>
            {/* Floating button */}
            <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                aria-label="Open Kea Devtools"
                title="Kea Devtools"
                style={{
                    position: 'fixed',
                    right: offset,
                    bottom: offset,
                    width: buttonSize,
                    height: buttonSize,
                    borderRadius: buttonSize / 2,
                    border: '1px solid rgba(0,0,0,0.1)',
                    boxShadow: '0 6px 22px rgba(0,0,0,0.18)',
                    background: '#fff',
                    cursor: 'pointer',
                    zIndex,
                    fontSize: Math.max(18, Math.floor(buttonSize * 0.42)),
                    lineHeight: 1,
                }}
            >
                🦜
            </button>

            {open ? (
                <div
                    role="dialog"
                    aria-modal="true"
                    style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.25)', zIndex }}
                    onClick={() => setOpen(false)}
                >
                    <div
                        onClick={(e) => e.stopPropagation()}
                        style={{
                            position: 'absolute',
                            right: offset,
                            bottom: offset + buttonSize + 12,
                            left: offset,
                            top: offset,
                            background: '#f7f8fa',
                            border: '1px solid rgba(0,0,0,0.08)',
                            borderRadius: 14,
                            boxShadow: '0 10px 40px rgba(0,0,0,0.2)',
                            overflow: 'hidden',
                            display: 'flex',
                            flexDirection: 'column',
                        }}
                    >
                        {header}

                        {activeTab === 'logics' ? (
                            <div style={{ display: 'flex', minHeight: 0, flex: 1 }}>
                                {/* Left panel */}
                                <div
                                    style={{
                                        width: 360,
                                        minWidth: 280,
                                        maxWidth: 480,
                                        borderRight: '1px solid rgba(0,0,0,0.08)',
                                        background: '#ffffff',
                                        display: 'flex',
                                        flexDirection: 'column',
                                    }}
                                >
                                    <div style={{ display: 'flex', gap: 6, padding: 8 }}>
                                        <input
                                            type="search"
                                            placeholder="Search logics…"
                                            value={query}
                                            onChange={(e) => setQuery(e.target.value)}
                                            style={inputStyle}
                                        />
                                        <select
                                            value={sortMode}
                                            onChange={(e) => setSortMode(e.target.value as SortMode)}
                                            style={inputStyle}
                                        >
                                            <option value="alpha">A → Z</option>
                                            <option value="recent">Recent</option>
                                        </select>
                                    </div>
                                    <div style={{ overflow: 'auto', padding: 6 }}>
                                        {visibleKeys.map((k) => {
                                            const logic = mounted[k]
                                            const active = selectedKey === k
                                            const name = displayName(logic)
                                            const size = logicSize(logic)
                                            const tint = Math.min(0.18, 0.04 + size * 0.01)
                                            return (
                                                <button
                                                    key={k}
                                                    type="button"
                                                    onClick={() => {
                                                        setSelectedKey(k)
                                                        recent.current.set(k, Date.now())
                                                    }}
                                                    title={k}
                                                    style={{
                                                        ...listItemStyle,
                                                        ...(active ? listItemActiveStyle : null),
                                                        background: active
                                                            ? `rgba(99,102,241,${tint + 0.08})`
                                                            : `rgba(99,102,241,${tint})`,
                                                    }}
                                                >
                                                    <div style={{ fontWeight: 700, textAlign: 'left' }}>{name}</div>
                                                    <div
                                                        style={{
                                                            color: 'rgba(0,0,0,0.6)',
                                                            fontSize: 12,
                                                            textAlign: 'left',
                                                            whiteSpace: 'nowrap',
                                                            overflow: 'hidden',
                                                            textOverflow: 'ellipsis',
                                                        }}
                                                    >
                                                        {k}
                                                    </div>
                                                </button>
                                            )
                                        })}
                                    </div>
                                </div>

                                {/* Right panel */}
                                <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
                                    {selectedLogic ? (
                                        <div
                                            style={{
                                                background: '#fff',
                                                border: '1px solid rgba(0,0,0,0.06)',
                                                borderRadius: 12,
                                                boxShadow: '0 2px 10px rgba(0,0,0,0.08)',
                                                padding: 12,
                                            }}
                                        >
                                            <div
                                                style={{
                                                    fontWeight: 800,
                                                    marginBottom: 6,
                                                }}
                                            >
                                                {selectedLogic.pathString}
                                            </div>
                                            <Connections
                                                logic={selectedLogic}
                                                onOpen={(path) => setSelectedKey(path)}
                                            />
                                            <ReverseConnections
                                                logic={selectedLogic}
                                                mounted={mounted}
                                                onOpen={(path) => setSelectedKey(path)}
                                            />
                                            <ActionsList logic={selectedLogic} />
                                            <Values logic={selectedLogic} />
                                        </div>
                                    ) : (
                                        <div style={{ color: 'rgba(0,0,0,0.6)' }}>Select a logic on the left.</div>
                                    )}
                                </div>
                            </div>
                        ) : (
                            <ActionsTab
                                actions={actions}
                                paused={paused}
                                onPauseToggle={() => setPaused((p) => !p)}
                                onClear={() => setActions([])}
                            />
                        )}
                    </div>
                </div>
            ) : null}
        </>
    )
}

/* ---------- Actions tab ---------- */

function ActionsTab({
    actions,
    paused,
    onPauseToggle,
    onClear,
}: {
    actions: ActionLogItem[]
    paused: boolean
    onPauseToggle: () => void
    onClear: () => void
}): JSX.Element {
    const [q, setQ] = useState('')
    const filtered = useMemo(() => {
        const s = q.trim().toLowerCase()
        if (!s) {
            return actions
        }
        return actions.filter(
            (a) =>
                a.type.toLowerCase().includes(s) ||
                (typeof a.payload === 'string' && a.payload.toLowerCase().includes(s))
        )
    }, [actions, q])

    return (
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, gap: 8, padding: 10, flex: 1 }}>
            <div style={{ display: 'flex', gap: 6 }}>
                <input
                    type="search"
                    placeholder="Filter actions…"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    style={inputStyle}
                />
                <button type="button" onClick={onPauseToggle} style={simpleBtnStyle}>
                    {paused ? 'Resume' : 'Pause'}
                </button>
                <button type="button" onClick={onClear} style={simpleBtnStyle}>
                    Clear
                </button>
            </div>
            <div
                style={{
                    flex: 1,
                    overflow: 'auto',
                    background: '#fff',
                    border: '1px solid rgba(0,0,0,0.06)',
                    borderRadius: 12,
                }}
            >
                {filtered.length === 0 ? (
                    <div style={{ padding: 12, color: 'rgba(0,0,0,0.6)' }}>No actions yet.</div>
                ) : (
                    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                        {filtered
                            .slice()
                            .reverse()
                            .map((a) => (
                                <li
                                    key={a.id}
                                    style={{ borderBottom: '1px solid rgba(0,0,0,0.05)', padding: '10px 12px' }}
                                >
                                    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                                        <code
                                            style={{
                                                fontWeight: 700,
                                                fontFamily:
                                                    'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                                            }}
                                        >
                                            {a.type}
                                        </code>
                                        <span style={{ color: 'rgba(0,0,0,0.5)', fontSize: 12 }}>
                                            {new Date(a.ts).toLocaleTimeString()}
                                        </span>
                                    </div>
                                    {a.payload !== undefined ? (
                                        <pre
                                            style={{
                                                margin: '6px 0 0',
                                                whiteSpace: 'pre-wrap',
                                                fontFamily:
                                                    'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                                            }}
                                        >
                                            {compactJSON(a.payload)}
                                        </pre>
                                    ) : null}
                                </li>
                            ))}
                    </ul>
                )}
            </div>
        </div>
    )
}

/* ---------- styles ---------- */

const inputStyle: React.CSSProperties = {
    flex: 1,
    border: '1px solid rgba(0,0,0,0.12)',
    background: '#fff',
    padding: '6px 8px',
    borderRadius: 8,
    outline: 'none',
}

const simpleBtnStyle: React.CSSProperties = {
    border: '1px solid rgba(0,0,0,0.12)',
    background: '#fff',
    padding: '6px 10px',
    borderRadius: 8,
    cursor: 'pointer',
}

function tabBtnStyle(active: boolean): React.CSSProperties {
    return {
        ...simpleBtnStyle,
        fontWeight: active ? 700 : 500,
        background: active ? '#eef2ff' : '#fff',
        borderColor: active ? 'rgba(0,0,0,0.18)' : 'rgba(0,0,0,0.12)',
    }
}

const listItemStyle: React.CSSProperties = {
    width: '100%',
    textAlign: 'left',
    padding: 10,
    border: '1px solid rgba(0,0,0,0.08)',
    borderRadius: 10,
    boxShadow: '0 1px 6px rgba(0,0,0,0.05)',
    marginBottom: 8,
    cursor: 'pointer',
    transition: 'background 120ms ease',
}

const listItemActiveStyle: React.CSSProperties = {
    borderColor: 'rgba(99,102,241,0.6)',
    boxShadow: '0 2px 10px rgba(99,102,241,0.18)',
}

const pill: React.CSSProperties = {
    border: '1px solid rgba(0,0,0,0.12)',
    background: '#fff',
    padding: '6px 8px',
    borderRadius: 999,
    cursor: 'pointer',
    fontSize: 12,
}
