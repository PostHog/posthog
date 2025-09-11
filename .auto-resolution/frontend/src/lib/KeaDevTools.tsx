// KeaDevtools.tsx
import { getContext } from 'kea'
import type { BuiltLogic, Context as KeaContext } from 'kea'
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { List, ListRowProps } from 'react-virtualized/dist/es/List'

type MountedMap = Record<string, BuiltLogic>
type SortMode = 'alpha' | 'recent'
type Tab = 'logics' | 'actions' | 'graph' | 'memory'

function useDebounce<T>(value: T, delay: number): T {
    const [debouncedValue, setDebouncedValue] = useState(value)

    useEffect(() => {
        const handler = setTimeout(() => {
            setDebouncedValue(value)
        }, delay)

        return () => {
            clearTimeout(handler)
        }
    }, [value, delay])

    return debouncedValue
}

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
    if (!logic || !logic.path || !logic.path.length) {
        return 'Unknown logic'
    }
    const parts = logic.path
    const hasKey = typeof logic.key !== 'undefined'

    if (hasKey && parts.length >= 2) {
        return parts.slice(-2).map(String).join('.')
    }

    return String(parts[parts.length - 1] || 'Unknown logic')
}

/** size metric → used for a subtle tint & node size */
function logicSize(logic: BuiltLogic): number {
    const c = Math.max(0, Object.keys((logic as any)?.connections || {}).length - 1)
    const a = Object.keys((logic as any)?.actions || {}).length
    const s = Object.keys((logic as any)?.selectors || {}).length
    const v = Object.keys((logic as any)?.values || {}).length
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
    const keys = Object.keys((logic as any).connections || {})
        .filter((k) => k !== (logic as any).pathString)
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
    const me = (logic as any).pathString
    const incoming = useMemo(() => {
        return Object.keys(mounted)
            .filter((k) => (mounted[k] as any)?.connections && (mounted[k] as any).connections[me] && k !== me)
            .sort((a, b) => a.localeCompare(b))
    }, [mounted, me])

    if (!incoming.length) {
        return null
    }
    return (
        <Section title="Logics that depend on this logic" count={incoming.length}>
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
    const keys = Object.keys((logic as any).actions || {}).sort((a, b) => a.localeCompare(b))
    if (!keys.length) {
        return null
    }

    const run = async (name: string): Promise<void> => {
        try {
            const raw = window.prompt(`Args for ${name} (JSON array)`, '[]')
            if (raw === null) {
                return
            }
            const args = raw.trim() === '' ? [] : (JSON.parse(raw) as any[])
            const fn = ((logic as any).actions as Record<string, (...a: any[]) => void>)[name]
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
    const keys = useMemo(
        () => Object.keys((logic as any).values || {}).sort((a, b) => a.localeCompare(b)),
        [(logic as any).values]
    )
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
                            value={compactJSON(((logic as any).values as Record<string, unknown>)[k])}
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

/* ---------- Key + Props summary ---------- */

function KeyAndProps({ logic }: { logic: BuiltLogic }): JSX.Element {
    const keyVal = (logic as any).key
    const propsVal = (logic as any).props
    return (
        <div
            style={{
                display: 'grid',
                gridTemplateColumns: 'max-content 1fr',
                columnGap: 12,
                rowGap: 6,
                alignItems: 'center',
                marginBottom: 8,
            }}
        >
            <div style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>Key</div>
            <textarea
                readOnly
                rows={1}
                value={compactJSON(keyVal)}
                style={{
                    width: '100%',
                    height: 28,
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                    resize: 'vertical',
                    border: '1px solid rgba(0,0,0,0.12)',
                    borderRadius: 6,
                    padding: '4px 6px',
                    background: '#fafafa',
                }}
            />
            <div style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>Props</div>
            <textarea
                readOnly
                rows={4}
                value={compactJSON(propsVal)}
                style={{
                    width: '100%',
                    height: 84,
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                    resize: 'vertical',
                    border: '1px solid rgba(0,0,0,0.12)',
                    borderRadius: 6,
                    padding: '4px 6px',
                    background: '#fafafa',
                }}
            />
        </div>
    )
}

/* ---------- GRAPH TAB ---------- */

type Node = {
    id: string
    name: string
    size: number
    x: number
    y: number
    vx: number
    vy: number
    fixed?: boolean
}
type Link = { source: string; target: string } // directed for highlights
type Undirected = { a: string; b: string } // for layout

function GraphTab({
    mounted,
    onOpen,
    highlightId,
}: {
    mounted: MountedMap
    onOpen: (path: string) => void
    highlightId?: string | null
}): JSX.Element {
    const width = 2400
    const height = 1500

    const { nodes, undirected, directed, outAdj, inAdj, avgDeg } = useMemo(() => {
        const keys = Object.keys(mounted)

        const degree: Record<string, number> = Object.fromEntries(keys.map((k) => [k, 0]))
        const undirectedSeen = new Set<string>()
        const undirected: Undirected[] = []
        const directed: Link[] = []

        const outAdj = new Map<string, Set<string>>(keys.map((k) => [k, new Set<string>()]))
        const inAdj = new Map<string, Set<string>>(keys.map((k) => [k, new Set<string>()]))

        for (const a of keys) {
            for (const b of Object.keys((mounted[a] as any)?.connections || {})) {
                if (!mounted[b] || a === b) {
                    continue
                }
                directed.push({ source: a, target: b })
                outAdj.get(a)!.add(b)
                inAdj.get(b)!.add(a)
                const u = a < b ? `${a}|${b}` : `${b}|${a}`
                if (!undirectedSeen.has(u)) {
                    undirectedSeen.add(u)
                    undirected.push({ a, b })
                    degree[a]++
                    degree[b]++
                }
            }
        }

        const degVals = Object.values(degree)
        const avgDeg = degVals.length ? degVals.reduce((s, d) => s + d, 0) / degVals.length : 0

        const nodes: Node[] = keys.map((k, i) => {
            const deg = degree[k] ?? 0
            const size = Math.max(8, Math.min(34, 8 + Math.sqrt(deg) * 6))
            const angle = (i / Math.max(1, keys.length)) * Math.PI * 2
            const r = 340 + (i % 200) * 3
            return {
                id: k,
                name: displayName(mounted[k]),
                size,
                x: width / 2 + Math.cos(angle) * r + (Math.random() - 0.5) * 80,
                y: height / 2 + Math.sin(angle) * r + (Math.random() - 0.5) * 80,
                vx: 0,
                vy: 0,
            }
        })

        return { nodes, undirected, directed, outAdj, inAdj, avgDeg }
    }, [mounted])

    // max spread constants
    const SPREAD = 3
    const LINK_DISTANCE = 180 * SPREAD + 30 * Math.log(nodes.length + 1)
    const SPRING = 0.06
    const CHARGE = (2600 + 300 * avgDeg) * SPREAD * SPREAD
    const DAMPING = 0.9
    const CENTER_PULL = 0.0015
    const COLLISION_PAD = 12

    // simulation
    const [searchOutNeighbors, setSearchOutNeighbors] = useState<Set<string>>(new Set())
    const [searchInNeighbors, setSearchInNeighbors] = useState<Set<string>>(new Set())
    const [searchHighlights, setSearchHighlights] = useState<Set<string>>(new Set())
    const [simRunning, setSimRunning] = useState(true)
    const nodesRef = useRef<Node[]>(nodes)
    const undirectedRef = useRef<Undirected[]>(undirected)
    const rafRef = useRef<number | null>(null)

    useEffect(() => {
        const prev = nodesRef.current
        nodesRef.current = nodes.map((n) => prev.find((p) => p.id === n.id) ?? { ...n })
        undirectedRef.current = undirected
        setSimRunning(true)
        return () => {
            if (rafRef.current) {
                cancelAnimationFrame(rafRef.current)
            }
            rafRef.current = null
        }
    }, [nodes, undirected])

    const [, force] = useState(0)
    const bump = (): void => force((t) => t + 1)

    useEffect(() => {
        if (!simRunning) {
            return
        }
        let last = performance.now()

        const tick = (): void => {
            const now = performance.now()
            const dt = Math.min(0.02, (now - last) / 1000)
            last = now

            const ns = nodesRef.current
            const ls = undirectedRef.current

            for (let i = 0; i < ns.length; i++) {
                for (let j = i + 1; j < ns.length; j++) {
                    const a = ns[i],
                        b = ns[j]
                    let dx = a.x - b.x,
                        dy = a.y - b.y
                    let d2 = dx * dx + dy * dy
                    if (d2 === 0) {
                        d2 = 0.01
                    }
                    const dist = Math.sqrt(d2)

                    const rep = (CHARGE * dt) / d2
                    const rx = (dx / dist) * rep,
                        ry = (dy / dist) * rep
                    if (!a.fixed) {
                        a.vx += rx
                        a.vy += ry
                    }
                    if (!b.fixed) {
                        b.vx -= rx
                        b.vy -= ry
                    }

                    const minD = a.size + b.size + COLLISION_PAD
                    if (dist < minD) {
                        const overlap = minD - dist
                        const nx = dx / (dist || 1),
                            ny = dy / (dist || 1)
                        if (!a.fixed) {
                            a.x += (overlap / 2) * nx
                            a.y += (overlap / 2) * ny
                            a.vx = 0
                            a.vy = 0
                        }
                        if (!b.fixed) {
                            b.x -= (overlap / 2) * nx
                            b.y -= (overlap / 2) * ny
                            b.vx = 0
                            b.vy = 0
                        }
                    }
                }
            }

            for (const l of ls) {
                const a = ns.find((n) => n.id === l.a)!,
                    b = ns.find((n) => n.id === l.b)!
                const dx = b.x - a.x,
                    dy = b.y - a.y
                const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy))
                const diff = dist - LINK_DISTANCE
                const f = diff * SPRING * dt
                const fx = (dx / dist) * f,
                    fy = (dy / dist) * f
                if (!a.fixed) {
                    a.vx += fx
                    a.vy += fy
                }
                if (!b.fixed) {
                    b.vx -= fx
                    b.vy -= fy
                }
            }

            const cx = width / 2,
                cy = height / 2
            let energy = 0
            for (const n of ns) {
                if (!n.fixed) {
                    n.vx += (cx - n.x) * CENTER_PULL
                    n.vy += (cy - n.y) * CENTER_PULL
                    n.vx *= DAMPING
                    n.vy *= DAMPING
                    n.x += n.vx
                    n.y += n.vy
                }
                energy += n.vx * n.vx + n.vy * n.vy
            }

            bump()
            if (energy < 0.0006) {
                rafRef.current = null
                return
            }
            rafRef.current = requestAnimationFrame(tick)
        }

        rafRef.current = requestAnimationFrame(tick)
        return () => {
            if (rafRef.current) {
                cancelAnimationFrame(rafRef.current)
            }
        }
    }, [simRunning, LINK_DISTANCE, CHARGE])

    // pan/zoom + drag (anchor zoom + no-jump drag + sticky hover)
    const [k, setK] = useState(1)
    const [tx, setTx] = useState(0)
    const [ty, setTy] = useState(0)
    const svgRef = useRef<SVGSVGElement | null>(null)
    const draggingId = useRef<string | null>(null)
    const dragOffset = useRef<{ dx: number; dy: number } | null>(null)
    const lastPan = useRef<{ x: number; y: number } | null>(null)

    const toWorld = (clientX: number, clientY: number): { x: number; y: number } => {
        const { left, top } = svgRef.current!.getBoundingClientRect()
        return { x: (clientX - left - tx) / k, y: (clientY - top - ty) / k }
    }

    const onWheel = (e: React.WheelEvent): void => {
        e.preventDefault()
        const { x: mx, y: my } = toWorld(e.clientX, e.clientY)
        const mult = Math.exp(-e.deltaY * 0.001)
        setK((prevK) => {
            const unclamped = prevK * mult
            const nextK = Math.min(4, Math.max(0.25, unclamped))
            const r = nextK / prevK
            setTx((prevTx) => (prevTx - mx) * r + mx)
            setTy((prevTy) => (prevTy - my) * r + my)
            return nextK
        })
    }

    const onMouseDownSVG = (e: React.MouseEvent): void => {
        if (draggingId.current) {
            return
        }
        lastPan.current = { x: e.clientX, y: e.clientY }
    }
    const onMouseMoveSVG = (e: React.MouseEvent): void => {
        if (!lastPan.current || draggingId.current) {
            return
        }
        const dx = e.clientX - lastPan.current.x,
            dy = e.clientY - lastPan.current.y
        lastPan.current = { x: e.clientX, y: e.clientY }
        setTx((t) => t + dx)
        setTy((t) => t + dy)
    }
    const onMouseUpSVG = (): void => {
        lastPan.current = null
    }

    const startDragNode =
        (id: string) =>
        (e: React.MouseEvent): void => {
            e.preventDefault()
            e.stopPropagation()
            draggingId.current = id
            lastPan.current = null
            const node = nodesRef.current.find((n) => n.id === id)!
            node.fixed = true
            const { x, y } = toWorld(e.clientX, e.clientY)
            dragOffset.current = { dx: x - node.x, dy: y - node.y }
            setHoveredId(id) // keep active while dragging
        }

    const onMouseMove = (e: React.MouseEvent): void => {
        if (!draggingId.current) {
            return
        }
        const node = nodesRef.current.find((n) => n.id === draggingId.current)!
        const { x, y } = toWorld(e.clientX, e.clientY)
        const off = dragOffset.current || { dx: 0, dy: 0 }
        node.x = x - off.dx
        node.y = y - off.dy
        node.vx = 0
        node.vy = 0
        bump()
    }
    const onMouseUp = (): void => {
        if (!draggingId.current) {
            return
        }
        const node = nodesRef.current.find((n) => n.id === draggingId.current)!
        node.fixed = false
        draggingId.current = null
        dragOffset.current = null
        setSimRunning(true)
    }

    // hover + highlighting state
    const [hoveredId, setHoveredId] = useState<string | null>(null)
    const outNeighbors = hoveredId ? (outAdj.get(hoveredId) ?? new Set<string>()) : new Set<string>()
    const inNeighbors = hoveredId ? (inAdj.get(hoveredId) ?? new Set<string>()) : new Set<string>()
    const bothNeighbors = new Set<string>([...outNeighbors].filter((x) => inNeighbors.has(x)))

    // apply external highlight (from "Show on graph")
    useEffect(() => {
        if (highlightId) {
            setHoveredId(highlightId)
            // Optional: nudge rendering
            bump()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [highlightId])

    // graph search
    const [search, setSearch] = useState('')
    useEffect(() => {
        const term = search.trim().toLowerCase()
        if (!term) {
            setSearchHighlights(new Set())
            setSearchOutNeighbors(new Set())
            setSearchInNeighbors(new Set())
            return
        }

        // match only by the label shown on the graph (displayName)
        const matches = new Set<string>()
        for (const n of nodesRef.current) {
            const nameL = n.name.toLowerCase()
            if (nameL.includes(term)) {
                matches.add(n.id)
            }
        }
        setSearchHighlights(matches)

        // if we're not hovering, also highlight dependencies (green/red) of all matches
        if (!hoveredId && matches.size) {
            const out = new Set<string>()
            const inc = new Set<string>()
            for (const id of matches) {
                for (const t of outAdj.get(id) ?? new Set<string>()) {
                    out.add(t)
                } // match -> target (green)
                for (const s of inAdj.get(id) ?? new Set<string>()) {
                    inc.add(s)
                } // source -> match (red)
            }
            setSearchOutNeighbors(out)
            setSearchInNeighbors(inc)
        } else {
            setSearchOutNeighbors(new Set())
            setSearchInNeighbors(new Set())
        }
    }, [search, hoveredId, outAdj, inAdj])
    const fillFor = (id: string): string => {
        if (id === hoveredId) {
            return '#FACC15'
        }
        if (!hoveredId) {
            if (searchHighlights.has(id)) {
                return '#FACC15'
            }
            const out = searchOutNeighbors.has(id)
            const inc = searchInNeighbors.has(id)
            if (out && inc) {
                return '#14B8A6'
            } // both directions
            if (out) {
                return 'rgba(34,197,94,0.9)'
            } // depends-on (green)
            if (inc) {
                return 'rgba(249,115,22,0.95)'
            } // depended-by (red/orange)
        }
        if (bothNeighbors.has(id)) {
            return '#14B8A6'
        }
        if (outNeighbors.has(id)) {
            return 'rgba(34,197,94,0.9)'
        } // outgoing neighbor
        if (inNeighbors.has(id)) {
            return 'rgba(249,115,22,0.95)'
        } // incoming neighbor
        return `rgba(99, 102, 241, 0.28)`
    }
    const labelWeight = (id: string): number =>
        id === hoveredId ||
        searchHighlights.has(id) ||
        (!hoveredId && (searchOutNeighbors.has(id) || searchInNeighbors.has(id))) ||
        outNeighbors.has(id) ||
        inNeighbors.has(id)
            ? 700
            : 400

    const labelOpacity = (id: string): number => {
        if (hoveredId) {
            return id === hoveredId || outNeighbors.has(id) || inNeighbors.has(id) ? 1 : 0.25
        }
        const isEmphasized = searchHighlights.has(id) || searchOutNeighbors.has(id) || searchInNeighbors.has(id)
        return isEmphasized ? 1 : 0.25
    }

    return (
        <div style={{ flex: 1, minHeight: 0, background: '#fff', borderTop: '1px solid rgba(0,0,0,0.06)' }}>
            <div style={{ padding: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                <button type="button" onClick={() => setSimRunning((s) => !s)} style={simpleBtnStyle}>
                    {simRunning ? 'Pause layout' : 'Resume layout'}
                </button>
                <button
                    type="button"
                    onClick={() => {
                        setK(1)
                        setTx(0)
                        setTy(0)
                    }}
                    style={simpleBtnStyle}
                >
                    Reset view
                </button>
                <input
                    type="search"
                    placeholder="Search graph…"
                    value={search || ''}
                    onChange={(e) => setSearch(e.target.value)}
                    style={{ ...inputStyle, maxWidth: 300 }}
                />
                <div style={{ marginLeft: 'auto', color: 'rgba(0,0,0,0.55)', fontSize: 12 }}>
                    Short names • Drag nodes • Scroll to zoom • Drag background to pan
                </div>
            </div>

            <svg
                ref={svgRef}
                width="100%"
                height="100%"
                viewBox={`0 0 ${width} ${height}`}
                style={{ display: 'block', cursor: draggingId.current ? 'grabbing' : 'grab' }}
                onWheel={onWheel}
                onMouseDown={onMouseDownSVG}
                onMouseMove={(e) => {
                    onMouseMoveSVG(e)
                    onMouseMove(e)
                }}
                onMouseUp={() => {
                    onMouseUpSVG()
                    onMouseUp()
                }}
                onMouseLeave={onMouseUp}
            >
                {/* faster marching ants */}
                <defs>
                    <style>{`
            .ants-fast { stroke-dasharray: 6 6; animation: ants 0.5s linear infinite; }
            @keyframes ants { to { stroke-dashoffset: -24; } }
          `}</style>
                </defs>

                <g transform={`translate(${tx},${ty}) scale(${k})`}>
                    {/* base links */}
                    <g stroke={hoveredId ? 'rgba(0,0,0,0.06)' : 'rgba(0,0,0,0.15)'} strokeWidth={1}>
                        {undirectedRef.current.map((l, i) => {
                            const a = nodesRef.current.find((n) => n.id === l.a)!
                            const b = nodesRef.current.find((n) => n.id === l.b)!
                            return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />
                        })}
                    </g>

                    {/* outgoing from hovered — animate TOWARDS hovered (reverse endpoints) */}
                    {hoveredId ? (
                        <g stroke="rgba(34,197,94,0.95)" strokeWidth={2} className="ants-fast">
                            {directed
                                .filter((l) => l.source === hoveredId)
                                .map((l, i) => {
                                    const h = nodesRef.current.find((n) => n.id === l.source)! // hovered
                                    const n = nodesRef.current.find((n) => n.id === l.target)! // neighbor
                                    // x1 = neighbor, x2 = hovered -> ants travel into hovered
                                    return <line key={`out-${i}`} x1={n.x} y1={n.y} x2={h.x} y2={h.y} />
                                })}
                        </g>
                    ) : null}

                    {/* incoming to hovered — animate AWAY from hovered */}
                    {hoveredId ? (
                        <g stroke="rgba(249,115,22,0.95)" strokeWidth={2} className="ants-fast">
                            {directed
                                .filter((l) => l.target === hoveredId)
                                .map((l, i) => {
                                    const h = nodesRef.current.find((n) => n.id === l.target)! // hovered
                                    const n = nodesRef.current.find((n) => n.id === l.source)! // neighbor
                                    // x1 = hovered, x2 = neighbor -> ants travel away from hovered
                                    return <line key={`in-${i}`} x1={h.x} y1={h.y} x2={n.x} y2={n.y} />
                                })}
                        </g>
                    ) : null}

                    {/* circles */}
                    {nodesRef.current.map((n) => (
                        <g
                            key={`c-${n.id}`}
                            transform={`translate(${n.x},${n.y})`}
                            onMouseEnter={() => setHoveredId(n.id)}
                            onMouseLeave={() => {
                                if (!draggingId.current) {
                                    setHoveredId(null)
                                }
                            }} // keep active while dragging
                            style={{ cursor: 'pointer' }}
                        >
                            <circle
                                r={n.size}
                                fill={fillFor(n.id)}
                                stroke={n.id === hoveredId ? '#CA8A04' : 'rgba(0,0,0,0.25)'}
                                onMouseDown={startDragNode(n.id)}
                                onClick={(e) => {
                                    e.stopPropagation()
                                    onOpen(n.id)
                                }}
                            />
                        </g>
                    ))}

                    {/* labels on top; fade non-neighbors when hovering */}
                    <g style={{ pointerEvents: 'none' }}>
                        {nodesRef.current.map((n) => (
                            <text
                                key={`t-${n.id}`}
                                x={n.x + n.size + 8}
                                y={n.y + 4}
                                fontSize={12}
                                fontWeight={labelWeight(n.id)}
                                fill="rgba(0,0,0,0.92)"
                                opacity={labelOpacity(n.id)}
                            >
                                {n.name}
                            </text>
                        ))}
                    </g>
                </g>
            </svg>
        </div>
    )
}

/* ---------- Memory tab helpers ---------- */
function formatBytes(bytes: number): string {
    if (!Number.isFinite(bytes) || bytes <= 0) {
        return '0 B'
    }
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let i = 0
    let n = bytes
    while (n >= 1024 && i < units.length - 1) {
        n /= 1024
        i++
    }
    if (i === 0) {
        return `${Math.trunc(n)} B`
    } // no fractional bytes
    const s = n.toFixed(n >= 100 ? 0 : n >= 10 ? 1 : 2).replace(/\.0+$/, '')
    return `${s} ${units[i]}`
}

// robust path walker for kea logic.path (array of strings/numbers)
function getAtPath(root: any, path: Array<string | number> | undefined): unknown {
    if (!root || !Array.isArray(path) || !path.length) {
        return undefined
    }
    let cur = root
    for (const seg of path) {
        if (cur == null) {
            return undefined
        }
        cur = cur[String(seg)]
    }
    return cur
}

// Limits to keep things safe
const INSPECT_MAX_DEPTH = 20
const INSPECT_MAX_ARRAY = 5_000

type InspectResult = { data: unknown; truncated: boolean }

// try/catch wrapper to protect against throwing getters/proxies
function tryGet<T>(fn: () => T): T | '[[Throw]]' {
    try {
        return fn()
    } catch {
        return '[[Throw]]'
    }
}

function toInspectable(
    value: unknown,
    maxDepth = INSPECT_MAX_DEPTH,
    seen = new WeakMap<object, any>(),
    depth = 0
): InspectResult {
    let truncated = false

    const visit = (v: any, d: number): any => {
        // primitives
        const t = typeof v
        if (v === null || t === 'string' || t === 'number' || t === 'boolean') {
            return v
        }
        if (t === 'bigint') {
            return v.toString()
        }
        if (t === 'symbol') {
            return v.toString()
        }
        if (t === 'function') {
            return `[Function ${v.name || 'anonymous'}]`
        }

        // depth limit
        if (d >= maxDepth) {
            truncated = true
            return '[MaxDepth]'
        }

        // typed arrays / buffers
        if (v instanceof Date) {
            return v.toISOString()
        }
        if (v instanceof ArrayBuffer) {
            return { __type: 'ArrayBuffer', byteLength: v.byteLength }
        }
        if (ArrayBuffer.isView(v) && !(v instanceof DataView)) {
            return { __type: v.constructor?.name || 'TypedArray', length: (v as any).length }
        }

        // cycles
        if (typeof v === 'object' && v !== null) {
            if (seen.has(v)) {
                return '[Circular]'
            }
        }

        // arrays
        if (Array.isArray(v)) {
            const out: any[] = []
            seen.set(v, out)
            const n = v.length
            const limit = Math.min(n, INSPECT_MAX_ARRAY)
            for (let i = 0; i < limit; i++) {
                out.push(
                    visit(
                        tryGet(() => v[i]),
                        d + 1
                    )
                )
            }
            if (n > limit) {
                truncated = true
                out.push(`[+${n - limit} more]`)
            }
            return out
        }

        // Map / Set
        if (v instanceof Map) {
            const out: any[] = []
            seen.set(v, out)
            let i = 0
            for (const [k, val] of v.entries()) {
                if (i++ >= INSPECT_MAX_ARRAY) {
                    truncated = true
                    out.push('[+more]')
                    break
                }
                out.push([visit(k, d + 1), visit(val, d + 1)])
            }
            return { __type: 'Map', entries: out }
        }
        if (v instanceof Set) {
            const out: any[] = []
            seen.set(v, out)
            let i = 0
            for (const val of v.values()) {
                if (i++ >= INSPECT_MAX_ARRAY) {
                    truncated = true
                    out.push('[+more]')
                    break
                }
                out.push(visit(val, d + 1))
            }
            return { __type: 'Set', values: out }
        }

        // generic object (protect against throwing property access)
        if (typeof v === 'object' && v !== null) {
            const out: Record<string, any> = {}
            seen.set(v, out)
            // own keys only
            const names = tryGet(() => Object.getOwnPropertyNames(v)) as any
            const syms = tryGet(() => Object.getOwnPropertySymbols(v)) as any
            const keys: (string | symbol)[] = []
            if (Array.isArray(names)) {
                keys.push(...names)
            }
            if (Array.isArray(syms)) {
                keys.push(...syms)
            }

            for (const k of keys) {
                // guard individual getter/proxy throws
                const val = tryGet(() => (v as any)[k as any])
                out[String(k)] = val === '[[Throw]]' ? '[Throwing Getter]' : visit(val, d + 1)
            }
            return out
        }

        // fallback
        return Object.prototype.toString.call(v)
    }

    const data = visit(value, depth)
    return { data, truncated }
}

function toJSONStringBestEffort(value: unknown, pretty = false): { text: string; truncated: boolean } {
    const { data, truncated } = toInspectable(value)
    try {
        return { text: JSON.stringify(data, null, pretty ? 2 : 0), truncated }
    } catch {
        return { text: '"[Unserializable]"', truncated: true }
    }
}

function safeStringify(x: unknown, pretty = false): string {
    return toJSONStringBestEffort(x, pretty).text
}

function byteLengthUTF8(s: string): number {
    try {
        return new TextEncoder().encode(s).length
    } catch {
        let bytes = 0
        for (let i = 0; i < s.length; i++) {
            const c = s.charCodeAt(i)
            bytes += c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0xd800 || c >= 0xe000 ? 3 : (i++, 4)
        }
        return bytes
    }
}

function bytesOf(value: unknown): number {
    try {
        const { text } = toJSONStringBestEffort(value, false)
        return byteLengthUTF8(text)
    } catch {
        // absolute fallback: best-effort string length
        try {
            return byteLengthUTF8(String(value))
        } catch {
            return 0
        }
    }
}

// Safe tag: avoids instanceof on cross-realm/host objects/proxies
function safeTag(v: unknown): string {
    try {
        return Object.prototype.toString.call(v) // e.g. "[object Map]"
    } catch {
        return '[object Unknown]'
    }
}

const isArray = (v: unknown): boolean => Array.isArray(v)
const isMap = (v: unknown): boolean => safeTag(v) === '[object Map]'
const isSet = (v: unknown): boolean => safeTag(v) === '[object Set]'
const isDate = (v: unknown): boolean => safeTag(v) === '[object Date]'
const isArrayBuffer = (v: unknown): boolean => safeTag(v) === '[object ArrayBuffer]'
const isDataView = (v: unknown): boolean => safeTag(v) === '[object DataView]'

function isTypedArray(v: unknown): boolean {
    const tag = safeTag(v)
    return (
        /\[object (?:Uint|Int|Float)\d{1,2}Array\]/.test(tag) ||
        tag === '[object BigInt64Array]' ||
        tag === '[object BigUint64Array]'
    )
}

// Hard guard for “host-like” things (DOM, React elements, Window, etc.)
function isHostLike(v: any): boolean {
    // React element (don’t traverse)
    if (v && typeof v === 'object' && (v as any).$$typeof) {
        return true
    }
    const tag = safeTag(v)
    // DOM-ish, window-ish, error objects, etc. — treat as leaf
    if (
        tag === '[object Window]' ||
        tag === '[object Document]' ||
        tag === '[object Element]' ||
        tag === '[object Node]' ||
        tag === '[object HTMLDocument]' ||
        tag === '[object ShadowRoot]' ||
        tag === '[object Error]'
    ) {
        return true
    }
    return false
}

function isComposite(v: unknown): boolean {
    if (v === null) {
        return false
    }
    if (typeof v !== 'object') {
        return false
    }
    if (isHostLike(v)) {
        return false
    }
    return true
}

type ChildWithSize = { key: string; value: unknown; bytes: number; canExpand: boolean }

function getChildrenSorted(value: unknown): ChildWithSize[] {
    const out: ChildWithSize[] = []
    if (value == null || !isComposite(value)) {
        return out
    }

    // Map
    if (isMap(value)) {
        let i = 0
        try {
            for (const [k, v] of (value as Map<any, any>).entries()) {
                if (i++ >= INSPECT_MAX_ARRAY) {
                    break
                }
                let kPreview = ''
                try {
                    const s = JSON.stringify(k)
                    kPreview = s.length > 80 ? s.slice(0, 77) + '…' : s
                } catch {
                    kPreview = String(k)
                }
                const b = bytesOf(v)
                out.push({ key: `→ ${kPreview}`, value: v, bytes: b, canExpand: isComposite(v) })
            }
        } catch {
            /* ignore */
        }
        out.sort((a, b) => b.bytes - a.bytes)
        return out
    }

    // Set
    if (isSet(value)) {
        let i = 0,
            idx = 0
        try {
            for (const v of (value as Set<any>).values()) {
                if (i++ >= INSPECT_MAX_ARRAY) {
                    break
                }
                const b = bytesOf(v)
                out.push({ key: String(idx++), value: v, bytes: b, canExpand: isComposite(v) })
            }
        } catch {
            /* ignore */
        }
        out.sort((a, b) => b.bytes - a.bytes)
        return out
    }

    // Array
    if (isArray(value)) {
        const arr = value as any[]
        const n = Math.min(arr.length, INSPECT_MAX_ARRAY)
        for (let i = 0; i < n; i++) {
            const got = tryGet(() => arr[i])
            const val = got === '[[Throw]]' ? '[Throwing Getter]' : got
            const b = bytesOf(val)
            out.push({ key: String(i), value: val, bytes: b, canExpand: isComposite(val) })
        }
        out.sort((a, b) => b.bytes - a.bytes)
        if (arr.length > n) {
            out.push({ key: `[+${arr.length - n} more]`, value: undefined, bytes: 0, canExpand: false })
        }
        return out
    }

    // Binary & dates: leaf-metadata only
    if (isArrayBuffer(value)) {
        const bl = tryGet(() => (value as ArrayBuffer).byteLength)
        out.push({ key: 'byteLength', value: bl, bytes: bytesOf(bl), canExpand: false })
        return out
    }
    if (isTypedArray(value) || isDataView(value)) {
        const len = tryGet(() => (value as any).length)
        out.push({ key: 'length', value: len, bytes: bytesOf(len), canExpand: false })
        return out
    }
    if (isDate(value)) {
        return out
    } // no children

    // Plain-ish object
    const keys: (string | symbol)[] = []
    const names = tryGet(() => Object.getOwnPropertyNames(value as object))
    const syms = tryGet(() => Object.getOwnPropertySymbols(value as object))
    if (Array.isArray(names)) {
        keys.push(...names)
    }
    if (Array.isArray(syms)) {
        keys.push(...syms)
    }

    for (const k of keys) {
        const got = tryGet(() => (value as any)[k as any])
        const val = got === '[[Throw]]' ? '[Throwing Getter]' : got
        const b = bytesOf(val)
        out.push({ key: String(k), value: val, bytes: b, canExpand: isComposite(val) })
        if (out.length >= INSPECT_MAX_ARRAY) {
            out.push({ key: '[+more]', value: undefined, bytes: 0, canExpand: false })
            break
        }
    }

    out.sort((a, b) => b.bytes - a.bytes)
    return out
}

function RowLine({
    depth,
    label,
    size,
    canExpand,
    isOpen,
    onToggle,
}: {
    depth: number
    label: string
    size: number
    canExpand: boolean
    isOpen: boolean
    onToggle: () => void
}): JSX.Element {
    return (
        <div
            style={{
                display: 'grid',
                gridTemplateColumns: '1fr max-content',
                alignItems: 'center',
                padding: '4px 6px',
                borderBottom: '1px dashed rgba(0,0,0,0.05)',
            }}
        >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ paddingLeft: depth * 14 }} />
                {canExpand ? (
                    <button
                        type="button"
                        onClick={onToggle}
                        style={simpleBtnStyle}
                        title={isOpen ? 'Collapse' : 'Expand'}
                    >
                        {isOpen ? '▾' : '▸'}
                    </button>
                ) : (
                    <span style={{ width: 32 }} />
                )}
                <code
                    style={{
                        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                        wordBreak: 'break-all',
                    }}
                >
                    {label}
                </code>
            </div>
            <div style={{ textAlign: 'right', fontWeight: 700 }}>{formatBytes(size)}</div>
        </div>
    )
}

type TreeState = { expanded: Set<string>; toggle: (id: string) => void }

function MemoryTree({
    rootValue,
    rootId,
    state,
    depth = 0,
}: {
    rootValue: unknown
    rootId: string
    state: TreeState
    depth?: number
}) {
    try {
        const children = getChildrenSorted(rootValue)
        return (
            <div>
                {children.map(({ key, value, bytes, canExpand }) => {
                    const id = `${rootId}.${key}`
                    const open = canExpand && state.expanded.has(id)
                    return (
                        <div key={id}>
                            <RowLine
                                depth={depth}
                                label={key}
                                size={bytes}
                                canExpand={canExpand}
                                isOpen={!!open}
                                onToggle={() => state.toggle(id)}
                            />
                            {open ? <MemoryTree rootValue={value} rootId={id} state={state} depth={depth + 1} /> : null}
                        </div>
                    )
                })}
            </div>
        )
    } catch (e: any) {
        return (
            <div style={{ padding: 6, color: 'rgba(0,0,0,0.7)' }}>
                <code>[[Render error: {e?.message ?? String(e)}]]</code>
            </div>
        )
    }
}

class MemoryErrorBoundary extends React.Component<{ children: React.ReactNode }, { hasError: boolean; msg?: string }> {
    constructor(props: any) {
        super(props)
        this.state = { hasError: false, msg: undefined }
    }

    static getDerivedStateFromError(err: any): Record<string, any> {
        return { hasError: true, msg: err?.message ?? String(err) }
    }

    componentDidCatch(err: any): void {
        console.warn('MemoryTree error', err)
    }

    render(): JSX.Element | null {
        if (this.state.hasError) {
            return (
                <div style={{ padding: 6, color: 'rgba(0,0,0,0.7)' }}>
                    <code>[[Tree crashed: {this.state.msg}]]</code>
                </div>
            )
        }
        return this.props.children as any
    }
}

// ---------- Memory tab ----------

type MemoryRow = {
    key: string
    name: string
    bytes: number
    value: unknown
}

function MemoryTab({ store, mounted }: { store: KeaContext['store']; mounted: MountedMap }): JSX.Element {
    const lastGood = useRef<Map<string, { text: string; bytes: number; value: unknown }>>(new Map())
    const [rows, setRows] = useState<MemoryRow[]>([])
    const [totalBytes, setTotalBytes] = useState(0)
    const [expanded, setExpanded] = useState<Set<string>>(new Set())
    const [isRefreshing, setIsRefreshing] = useState(false)
    const [lastUpdated, setLastUpdated] = useState<number | null>(null)

    // single recompute from a consistent snapshot
    const recompute = React.useCallback(() => {
        setIsRefreshing(true)

        // snapshot once
        const state = store.getState()
        const keys = Object.keys(mounted)

        // build rows from snapshot
        const nextRows: MemoryRow[] = keys.map((pathString) => {
            const logic = mounted[pathString]
            const value = getAtPath(state, (logic as any)?.path)

            // Best-effort JSON
            const { text } = toJSONStringBestEffort(value, false)
            const bytes = byteLengthUTF8(text)

            // Heuristic: if it's an object-like value but serialized to something suspiciously tiny,
            // keep the last good snapshot (prevents collapsing to 15 B).
            const looksTiny = typeof value === 'object' && value !== null && bytes < 40 /* ~ "[{}]" scale */

            const prior = lastGood.current.get(pathString)
            if (looksTiny && prior && prior.bytes > bytes) {
                return { key: pathString, name: displayName(logic), bytes: prior.bytes, value: prior.value }
            }

            // Update last good if this is meaningful
            if (!looksTiny || bytes > (prior?.bytes ?? 0)) {
                lastGood.current.set(pathString, { text, bytes, value })
            }

            return { key: pathString, name: displayName(logic), bytes, value }
        })

        nextRows.sort((a, b) => b.bytes - a.bytes)

        // ✅ total is the sum of Kea slices, not a risky whole-store stringify
        const nextTotalBytes = nextRows.reduce((acc, r) => acc + r.bytes, 0)

        setRows(nextRows)
        setTotalBytes(nextTotalBytes)
        setLastUpdated(Date.now())
        setIsRefreshing(false)
    }, [store, mounted])

    // run once on mount
    useEffect(() => {
        recompute()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    // also refresh on store changes (coalesced)
    useEffect(() => {
        let raf: number | null = null
        const unsub = store.subscribe(() => {
            if (raf !== null) {
                return
            }
            raf = requestAnimationFrame(() => {
                raf = null
                recompute()
            })
        })
        return () => {
            unsub()
            if (raf !== null) {
                cancelAnimationFrame(raf)
            }
        }
    }, [store, recompute])

    const toggle = (k: string): void =>
        setExpanded((prev) => {
            const next = new Set(prev)
            next.has(k) ? next.delete(k) : next.add(k)
            return next
        })

    const copyJSON = async (k: string): Promise<void> => {
        const row = rows.find((r) => r.key === k)
        try {
            await navigator.clipboard.writeText(safeStringify(row?.value, true))
            alert('Copied JSON to clipboard.')
        } catch (e: any) {
            alert(`Copy failed: ${e?.message ?? e}`)
        }
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, padding: 10, gap: 8, flex: 1 }}>
            <div
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    background: '#fff',
                    border: '1px solid rgba(0,0,0,0.06)',
                    borderRadius: 12,
                    padding: 12,
                }}
            >
                <div style={{ fontWeight: 800, fontSize: 16 }}>Memory usage</div>
                <div style={{ marginLeft: 'auto', color: 'rgba(0,0,0,0.7)' }}>
                    Store size: <strong>{formatBytes(totalBytes)}</strong>
                    {lastUpdated ? (
                        <span style={{ marginLeft: 10, fontSize: 12, color: 'rgba(0,0,0,0.55)' }}>
                            Updated {new Date(lastUpdated).toLocaleTimeString()}
                        </span>
                    ) : null}
                </div>
                <button
                    type="button"
                    onClick={recompute}
                    disabled={isRefreshing}
                    style={{ ...simpleBtnStyle, minWidth: 90, display: 'inline-flex', gap: 6, alignItems: 'center' }}
                    title="Recompute from current store snapshot"
                >
                    {isRefreshing ? (
                        <>
                            <span
                                aria-hidden
                                style={{
                                    width: 14,
                                    height: 14,
                                    borderRadius: '50%',
                                    border: '2px solid rgba(0,0,0,0.25)',
                                    borderTopColor: 'rgba(0,0,0,0.6)',
                                    display: 'inline-block',
                                    animation: 'spin 0.9s linear infinite',
                                }}
                            />
                            Refreshing…
                        </>
                    ) : (
                        'Refresh'
                    )}
                </button>
                {/* local keyframes for spinner */}
                <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
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
                {rows.length === 0 ? (
                    <div style={{ padding: 12, color: 'rgba(0,0,0,0.6)' }}>No mounted logics.</div>
                ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
                        <thead style={{ position: 'sticky', top: 0, background: '#fafafa', zIndex: 1 }}>
                            <tr>
                                <th
                                    style={{
                                        textAlign: 'left',
                                        padding: '10px 12px',
                                        borderBottom: '1px solid rgba(0,0,0,0.06)',
                                        width: '45%',
                                    }}
                                >
                                    Logic
                                </th>
                                <th
                                    style={{
                                        textAlign: 'right',
                                        padding: '10px 12px',
                                        borderBottom: '1px solid rgba(0,0,0,0.06)',
                                        width: '10%',
                                    }}
                                >
                                    Size
                                </th>
                                <th
                                    style={{
                                        textAlign: 'left',
                                        padding: '10px 12px',
                                        borderBottom: '1px solid rgba(0,0,0,0.06)',
                                    }}
                                >
                                    Actions
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((r) => {
                                const isOpen = expanded.has(r.key)
                                return (
                                    <React.Fragment key={r.key}>
                                        <tr style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
                                            <td style={{ padding: '10px 12px', verticalAlign: 'top' }}>
                                                <div style={{ fontWeight: 700 }}>{r.name}</div>
                                                <div
                                                    style={{
                                                        marginTop: 4,
                                                        color: 'rgba(0,0,0,0.6)',
                                                        fontSize: 12,
                                                        wordBreak: 'break-all',
                                                    }}
                                                    title={r.key}
                                                >
                                                    {r.key}
                                                </div>
                                            </td>
                                            <td
                                                style={{
                                                    padding: '10px 12px',
                                                    verticalAlign: 'top',
                                                    textAlign: 'right',
                                                    fontWeight: 700,
                                                }}
                                            >
                                                {formatBytes(r.bytes)}
                                            </td>
                                            <td style={{ padding: '10px 12px', verticalAlign: 'top' }}>
                                                <div style={{ display: 'flex', gap: 8 }}>
                                                    <button
                                                        type="button"
                                                        onClick={() => toggle(r.key)}
                                                        style={simpleBtnStyle}
                                                        title={
                                                            isOpen ? 'Collapse details' : 'Expand to see per-key sizes'
                                                        }
                                                    >
                                                        {isOpen ? 'Collapse' : 'Expand'}
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => copyJSON(r.key)}
                                                        style={simpleBtnStyle}
                                                        title="Copy JSON to clipboard"
                                                    >
                                                        Copy JSON
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                        {isOpen ? (
                                            <tr>
                                                <td colSpan={3} style={{ padding: '6px 12px 12px' }}>
                                                    <div
                                                        style={{
                                                            border: '1px solid rgba(0,0,0,0.12)',
                                                            borderRadius: 8,
                                                            background: '#fafafa',
                                                            overflow: 'hidden',
                                                        }}
                                                    >
                                                        <div
                                                            style={{
                                                                display: 'grid',
                                                                gridTemplateColumns: '1fr max-content',
                                                                padding: '8px 10px',
                                                                background: '#f0f1f5',
                                                                borderBottom: '1px solid rgba(0,0,0,0.08)',
                                                                fontWeight: 700,
                                                            }}
                                                        >
                                                            <div>{r.key}</div>
                                                            <div>{formatBytes(r.bytes)}</div>
                                                        </div>

                                                        <MemoryErrorBoundary>
                                                            <MemoryTree
                                                                rootValue={r.value}
                                                                rootId={r.key}
                                                                state={{
                                                                    expanded,
                                                                    toggle: (id) =>
                                                                        setExpanded((prev) => {
                                                                            const next = new Set(prev)
                                                                            next.has(id)
                                                                                ? next.delete(id)
                                                                                : next.add(id)
                                                                            return next
                                                                        }),
                                                                }}
                                                            />
                                                        </MemoryErrorBoundary>
                                                    </div>
                                                </td>
                                            </tr>
                                        ) : null}
                                    </React.Fragment>
                                )
                            })}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    )
}

/* ---------- main component ---------- */

export function KeaDevtools({
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

    // highlight for graph ("Show on graph")
    const [graphHighlight, setGraphHighlight] = useState<string | null>(null)

    const { mount, store } = getContext() as KeaContext
    const mounted = ((mount as any)?.mounted ?? {}) as MountedMap

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
                    // Prepend new action to show newest first (avoids reversing later)
                    const next = [entry, ...prev]
                    if (next.length > maxActions) {
                        // Remove oldest items from the end
                        next.splice(maxActions)
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

    // keys + default selection
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

    // Debounce the search query for better performance
    const debouncedQuery = useDebounce(query, 300)

    // left list: filter + sort
    const visibleKeys = useMemo(() => {
        const q = debouncedQuery.trim().toLowerCase()
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
    }, [allKeys, sortMode, debouncedQuery, mounted])

    const selectedLogic = selectedKey ? mounted[selectedKey] : undefined

    const header = (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px' }}>
            <div style={{ fontWeight: 800, fontSize: 16 }}>Kea Devtools</div>
            {activeTab === 'logics' ? (
                <div style={{ color: 'rgba(0,0,0,0.55)' }}>{allKeys.length} mounted</div>
            ) : activeTab === 'actions' ? (
                <div style={{ color: 'rgba(0,0,0,0.55)' }}>{actions.length} actions</div>
            ) : activeTab === 'graph' ? (
                <div style={{ color: 'rgba(0,0,0,0.55)' }}>Graph of {allKeys.length} logics</div>
            ) : activeTab === 'memory' ? (
                <div style={{ color: 'rgba(0,0,0,0.55)' }}>Memory usage</div>
            ) : (
                <div style={{ color: 'rgba(0,0,0,0.55)' }}>{activeTab}</div>
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
                <button type="button" onClick={() => setActiveTab('graph')} style={tabBtnStyle(activeTab === 'graph')}>
                    Graph
                </button>
                <button
                    type="button"
                    onClick={() => setActiveTab('memory')}
                    style={tabBtnStyle(activeTab === 'memory')}
                    title="Analyze store size by logic"
                >
                    Memory
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
                    left: offset,
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
                                            value={query || ''}
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
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: 8,
                                                    marginBottom: 6,
                                                }}
                                            >
                                                <div style={{ fontWeight: 800 }}>
                                                    {(selectedLogic as any).pathString}
                                                </div>
                                                <div style={{ marginLeft: 'auto' }} />
                                                <button
                                                    type="button"
                                                    onClick={() => {
                                                        setGraphHighlight((selectedLogic as any).pathString)
                                                        setActiveTab('graph')
                                                    }}
                                                    style={simpleBtnStyle}
                                                >
                                                    Show on graph
                                                </button>
                                            </div>

                                            {/* Key + Props */}
                                            <KeyAndProps logic={selectedLogic} />

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
                        ) : activeTab === 'actions' ? (
                            <ActionsTab
                                actions={actions}
                                paused={paused}
                                onPauseToggle={() => setPaused((p) => !p)}
                                onClear={() => setActions([])}
                            />
                        ) : activeTab === 'graph' ? (
                            <GraphTab
                                mounted={mounted}
                                onOpen={(path) => setSelectedKey(path)}
                                highlightId={graphHighlight ?? undefined}
                            />
                        ) : activeTab === 'memory' ? (
                            <MemoryTab store={store} mounted={mounted} />
                        ) : (
                            <></>
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
    const [expanded, setExpanded] = useState<Set<number>>(new Set())

    // Debounce the search query for better performance
    const debouncedQ = useDebounce(q, 300)

    const filtered = useMemo(() => {
        const s = debouncedQ.trim().toLowerCase()
        if (!s) {
            return actions
        }
        return actions.filter(
            (a) =>
                a.type.toLowerCase().includes(s) ||
                (typeof a.payload === 'string' && a.payload.toLowerCase().includes(s))
        )
    }, [actions, debouncedQ])

    const toggleExpanded = (id: number): void => {
        setExpanded((prev) => {
            const next = new Set(prev)
            if (next.has(id)) {
                next.delete(id)
            } else {
                next.add(id)
            }
            return next
        })
    }

    const oneLine = (x: unknown): string => {
        try {
            // compact JSON to a single line; do not add ellipsis here
            return JSON.stringify(x)
        } catch {
            return String(x)
        }
    }

    const pretty = (x: unknown): string => {
        try {
            return JSON.stringify(x, null, 2)
        } catch {
            return String(x)
        }
    }

    // Calculate dynamic row height based on whether payload is expanded
    const getRowHeight = ({ index }: { index: number }): number => {
        const action = filtered[index]
        if (!action) {
            return 80
        }
        const isOpen = expanded.has(action.id)
        if (isOpen) {
            // Estimate height based on payload size
            const lines = pretty(action.payload).split('\n').length
            return Math.min(80 + lines * 20, 600) // Cap at 600px
        }
        return 80 // Default height for collapsed rows
    }

    // Row renderer for virtualized list
    const renderRow = ({ index, key, style }: ListRowProps): JSX.Element => {
        const action = filtered[index]
        if (!action) {
            return <div key={key} style={style} />
        }

        const isOpen = expanded.has(action.id)

        return (
            <div
                key={key}
                style={{
                    ...style,
                    display: 'flex',
                    borderBottom: '1px solid rgba(0,0,0,0.05)',
                    background: '#fff',
                }}
            >
                {/* Left column: action + time */}
                <div
                    style={{
                        width: '40%',
                        padding: '10px 12px',
                        borderRight: '1px solid rgba(0,0,0,0.06)',
                    }}
                >
                    <div>
                        <code
                            style={{
                                fontWeight: 700,
                                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                                wordBreak: 'break-word',
                            }}
                        >
                            {action.type}
                        </code>
                    </div>
                    <div
                        style={{
                            marginTop: 4,
                            color: 'rgba(0,0,0,0.6)',
                            fontSize: 12,
                        }}
                        title={new Date(action.ts).toISOString()}
                    >
                        {new Date(action.ts).toLocaleString()}
                    </div>
                </div>

                {/* Right column: payload */}
                <div
                    style={{
                        flex: 1,
                        padding: '10px 12px',
                        display: 'flex',
                        gap: 8,
                        alignItems: 'flex-start',
                        minWidth: 0, // Allow flex item to shrink below content width
                    }}
                >
                    <div
                        style={{
                            flex: 1,
                            height: isOpen ? 'calc(100% - 20px)' : 'auto',
                            maxWidth: isOpen ? '600px' : '300px',
                            whiteSpace: isOpen ? 'pre-wrap' : 'nowrap',
                            overflow: isOpen ? 'auto' : 'hidden',
                            textOverflow: isOpen ? 'clip' : 'ellipsis',
                            wordBreak: isOpen ? 'break-word' : 'normal',
                            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                        }}
                    >
                        {action.payload === undefined ? '—' : isOpen ? pretty(action.payload) : oneLine(action.payload)}
                    </div>
                    <button
                        type="button"
                        onClick={() => toggleExpanded(action.id)}
                        style={{ ...simpleBtnStyle, marginLeft: 'auto', flexShrink: 0 }}
                        title={isOpen ? 'Collapse payload' : 'Expand payload'}
                    >
                        {isOpen ? 'Collapse' : 'Expand'}
                    </button>
                </div>
            </div>
        )
    }

    // Create a ref for the List to trigger re-render when expanded state changes
    const listRef = useRef<List>(null)

    // Force re-render of list when expanded state changes
    useEffect(() => {
        listRef.current?.recomputeRowHeights()
    }, [expanded])

    return (
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, gap: 8, padding: 10, flex: 1 }}>
            <div style={{ display: 'flex', gap: 6 }}>
                <input
                    type="search"
                    placeholder="Filter actions…"
                    value={q || ''}
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
                    background: '#fff',
                    border: '1px solid rgba(0,0,0,0.06)',
                    borderRadius: 12,
                    position: 'relative',
                }}
            >
                {/* Header */}
                <div
                    style={{
                        display: 'flex',
                        position: 'sticky',
                        top: 0,
                        background: '#fafafa',
                        borderBottom: '1px solid rgba(0,0,0,0.06)',
                        zIndex: 1,
                    }}
                >
                    <div
                        style={{
                            width: '40%',
                            padding: '10px 12px',
                            fontWeight: 700,
                            borderRight: '1px solid rgba(0,0,0,0.06)',
                        }}
                    >
                        Action • Date
                    </div>
                    <div
                        style={{
                            flex: 1,
                            padding: '10px 12px',
                            fontWeight: 700,
                        }}
                    >
                        Payload
                    </div>
                </div>

                {/* Content */}
                <div style={{ height: 'calc(100% - 41px)' }}>
                    {filtered.length === 0 ? (
                        <div style={{ padding: 12, color: 'rgba(0,0,0,0.6)' }}>No actions yet.</div>
                    ) : (
                        <AutoSizer>
                            {({ height, width }) => (
                                <List
                                    ref={listRef}
                                    width={width}
                                    height={height}
                                    rowCount={filtered.length}
                                    rowHeight={getRowHeight}
                                    rowRenderer={renderRow}
                                    overscanRowCount={10}
                                />
                            )}
                        </AutoSizer>
                    )}
                </div>
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
