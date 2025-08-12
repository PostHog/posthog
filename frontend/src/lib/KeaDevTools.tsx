// KeaDevtools.tsx
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { getContext } from 'kea'
import type { BuiltLogic, Context as KeaContext } from 'kea'

type MountedMap = Record<string, BuiltLogic>
type SortMode = 'alpha' | 'recent'
type Tab = 'logics' | 'actions' | 'graph'

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
        const keyStr = String((logic as any).key)
        const keyIndex = parts.lastIndexOf(keyStr)
        if (keyIndex > 0) {
            const name = parts[keyIndex - 1]
            return `${name}.${keyStr}`
        }
    }

    return parts[parts.length - 1]
}

/** size metric → used for a subtle tint & node size */
function logicSize(logic: BuiltLogic): number {
    const c = Math.max(0, Object.keys((logic as any).connections || {}).length - 1)
    const a = Object.keys((logic as any).actions || {}).length
    const s = Object.keys((logic as any).selectors || {}).length
    const v = Object.keys((logic as any).values || {}).length
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

                    // hard non-overlap
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
            ) : activeTab === 'actions' ? (
                <div style={{ color: 'rgba(0,0,0,0.55)' }}>{actions.length} actions</div>
            ) : (
                <div style={{ color: 'rgba(0,0,0,0.55)' }}>Graph of {allKeys.length} logics</div>
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
                        ) : (
                            <GraphTab
                                mounted={mounted}
                                onOpen={(path) => setSelectedKey(path)}
                                highlightId={graphHighlight ?? undefined}
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
                                        <span
                                            style={{
                                                color: 'rgba(0,0,0,0.5)',
                                                fontSize: 12,
                                            }}
                                        >
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
