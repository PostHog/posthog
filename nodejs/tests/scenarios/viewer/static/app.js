const app = document.getElementById('app')
const tooltip = document.getElementById('tooltip')
const SVG = 'http://www.w3.org/2000/svg'

const SERIES = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`)

// ---------- small helpers ----------

const h = (tag, attrs = {}, ...children) => {
    const el = document.createElement(tag)
    for (const [key, value] of Object.entries(attrs)) {
        if (value === undefined || value === null || value === false) {
            continue
        }
        if (key === 'class') {
            el.className = value
        } else if (key.startsWith('on')) {
            el.addEventListener(key.slice(2), value)
        } else if (key === 'style') {
            el.setAttribute('style', value)
        } else {
            el.setAttribute(key, value)
        }
    }
    for (const child of children.flat(Infinity)) {
        if (child !== undefined && child !== null && child !== false) {
            el.append(child instanceof Node ? child : document.createTextNode(String(child)))
        }
    }
    return el
}

const s = (tag, attrs = {}, ...children) => {
    const el = document.createElementNS(SVG, tag)
    for (const [key, value] of Object.entries(attrs)) {
        if (value !== undefined && value !== null) {
            el.setAttribute(key, value)
        }
    }
    for (const child of children.flat(Infinity)) {
        if (child !== undefined && child !== null) {
            el.append(child instanceof Node ? child : document.createTextNode(String(child)))
        }
    }
    return el
}

const render = (...children) =>
    app.replaceChildren(
        ...children.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false)
    )

const getJson = async (url) => {
    // This file runs in the browser, where the Node request util does not exist.
    // oxlint-disable-next-line no-restricted-globals
    const response = await fetch(url)
    if (!response.ok) {
        throw new Error(`${url} answered ${response.status}`)
    }
    return response.json()
}

const fmtDuration = (ms) => {
    if (ms === null || ms === undefined) {
        return '-'
    }
    const seconds = Math.round(ms / 1000)
    if (seconds < 60) {
        return `${seconds}s`
    }
    const minutes = Math.floor(seconds / 60)
    const rest = seconds % 60
    return rest ? `${minutes}m ${rest}s` : `${minutes}m`
}

const fmtNumber = (value, digits = 1) => {
    if (value === null || value === undefined || Number.isNaN(value)) {
        return '-'
    }
    if (Math.abs(value) >= 100) {
        return Math.round(value).toLocaleString()
    }
    return Number(value.toFixed(digits)).toLocaleString()
}

const fmtBytes = (bytes) => (bytes === null || bytes === undefined ? '-' : `${fmtNumber(bytes / 1024 / 1024, 0)} MB`)

const fmtTime = (iso) =>
    new Date(iso).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    })

const ago = (iso) => {
    const minutes = Math.round((Date.now() - Date.parse(iso)) / 60000)
    if (minutes < 1) {
        return 'just now'
    }
    if (minutes < 60) {
        return `${minutes} min ago`
    }
    const hours = Math.round(minutes / 60)
    return hours < 48 ? `${hours} h ago` : `${Math.round(hours / 24)} days ago`
}

const statusPill = (status) => h('span', { class: `status ${status}` }, status)

const doseText = (valve, dose) => {
    const parts = Object.entries(dose ?? {}).map(([key, value]) => `${key} ${value}`)
    return parts.length ? parts.join(', ') : ''
}

const valveText = (entry) => {
    const when = entry.when
        ? `when ${entry.when.atLeast}+ jobs run on ${entry.when.queue}`
        : `at ${fmtDuration(entry.atMs)}`
    const dose = doseText(entry.valve, entry.dose)
    return `${entry.valve} on ${entry.target}${dose ? ` (${dose})` : ''}, ${when}, for ${fmtDuration(entry.forMs)}`
}

const trafficText = ({ name, ratePerSecond }) =>
    ratePerSecond === null ? name : `${name} ${fmtNumber(ratePerSecond)}/s`

const showTooltip = (event, html) => {
    tooltip.innerHTML = html
    tooltip.hidden = false
    const { innerWidth } = window
    const x = event.clientX + 14
    tooltip.style.left = `${Math.min(x, innerWidth - tooltip.offsetWidth - 8)}px`
    tooltip.style.top = `${event.clientY + 14}px`
}

const hideTooltip = () => {
    tooltip.hidden = true
}

// ---------- the delivery path ----------

const NODE_W = 182
const NODE_H = 82

const NODES = [
    { id: 'generator', name: 'Load generator', role: 'scenario runner', x: 10, y: 170 },
    { id: 'kafka', name: 'Event stream', role: 'Kafka, events topic', x: 232, y: 50 },
    { id: 'cdp-api', name: 'Send API', role: 'cdp-api', x: 232, y: 290 },
    { id: 'cdp-processed-events', name: 'Workflow trigger', role: 'cdp-processed-events', x: 454, y: 50 },
    { id: 'postgres', name: 'Job queue database', role: 'Cyclotron Postgres', x: 676, y: 170 },
    { id: 'cdp-cyclotron-v2-janitor', name: 'Stuck job cleanup', role: 'cdp-cyclotron-v2-janitor', x: 676, y: 320 },
    { id: 'cdp-ses-webhooks', name: 'Email feedback intake', role: 'cdp-ses-webhooks', x: 454, y: 380 },
    {
        id: 'cdp-cyclotron-worker-hogflow',
        name: 'Workflow runner',
        role: 'cdp-cyclotron-worker-hogflow',
        x: 898,
        y: 50,
    },
    { id: 'cdp-cyclotron-worker-email', name: 'Email sender', role: 'cdp-cyclotron-worker-email', x: 898, y: 290 },
    { id: 'hooks', name: 'Customer webhooks', role: 'fake hooks.example.com', x: 1120, y: 50 },
    { id: 'ses', name: 'Email provider', role: 'fake SES', x: 1120, y: 290 },
]

const NODE_BY_ID = Object.fromEntries(NODES.map((node) => [node.id, node]))

const TARGET_NODE = {
    postgres: 'postgres',
    cyclotron: 'postgres',
    ses: 'ses',
    'hooks.example.com': 'hooks',
}

const nodeOfTarget = (target) => TARGET_NODE[target] ?? (NODE_BY_ID[target] ? target : undefined)

const plainOf = (target) => {
    const id = nodeOfTarget(target)
    return id ? NODE_BY_ID[id].name.toLowerCase() : target
}

const VALVE_PLAIN = {
    'role.kill': (name) => `Kills the ${name}`,
    'role.freeze': (name) => `Freezes the ${name}`,
    'pg.drop_connections': (name) => `Drops connections to the ${name}`,
    'pg.failover': (name) => `Fails over the ${name}`,
    'dest.status': (name, dose) => `Makes the ${name} answer ${dose.code ?? 'with errors'}`,
    'ses.throttle': (name, dose) => `Throttles the ${name}${dose.rate ? ` to ${dose.rate} a second` : ''}`,
    'ses.reject': (name) => `Makes the ${name} reject mail`,
}

const valvePlain = ({ valve, target, dose }) =>
    (VALVE_PLAIN[valve] ?? ((name) => `${valve} on the ${name}`))(plainOf(target), dose ?? {})

const INVARIANT_PLAIN = {
    at_least_once: () => 'every message arrives',
    duplicate_sends: (gate) =>
        gate === null
            ? 'duplicate sends counted'
            : gate === 0
              ? 'no duplicate sends'
              : `at most ${gate} duplicate sends`,
    refused_at_intake: (gate) =>
        gate === null || gate === 0 ? 'nothing refused at intake' : `at most ${gate} refused at intake`,
    bounced_suppressed: () => 'bounced addresses get suppressed',
    resident_backlog_intact: () => 'jobs already queued survive',
}

const invariantPlain = (name, gate = null) =>
    INVARIANT_PLAIN[name]?.(gate) ?? (gate === null ? name : `${name} ≤ ${gate}`)

const right = (n) => [n.x + NODE_W, n.y + NODE_H / 2]
const left = (n) => [n.x, n.y + NODE_H / 2]
const top = (n) => [n.x + NODE_W / 2, n.y]
const bottom = (n) => [n.x + NODE_W / 2, n.y + NODE_H]

const curve = ([x1, y1], [x2, y2]) => {
    const dx = Math.max(Math.abs(x2 - x1) / 2, 30)
    return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`
}

const LINKS = [
    { id: 'gen-kafka', d: () => curve(right(NODE_BY_ID.generator), left(NODE_BY_ID.kafka)) },
    { id: 'gen-api', d: () => curve(right(NODE_BY_ID.generator), left(NODE_BY_ID['cdp-api'])) },
    { id: 'kafka-events', d: () => curve(right(NODE_BY_ID.kafka), left(NODE_BY_ID['cdp-processed-events'])) },
    { id: 'events-pg', d: () => curve(right(NODE_BY_ID['cdp-processed-events']), left(NODE_BY_ID.postgres)) },
    { id: 'api-pg', d: () => curve(right(NODE_BY_ID['cdp-api']), left(NODE_BY_ID.postgres)) },
    {
        id: 'pg-hogflow',
        d: () => curve(right(NODE_BY_ID.postgres), left(NODE_BY_ID['cdp-cyclotron-worker-hogflow'])),
    },
    { id: 'pg-email', d: () => curve(right(NODE_BY_ID.postgres), left(NODE_BY_ID['cdp-cyclotron-worker-email'])) },
    { id: 'hogflow-hooks', d: () => curve(right(NODE_BY_ID['cdp-cyclotron-worker-hogflow']), left(NODE_BY_ID.hooks)) },
    { id: 'email-ses', d: () => curve(right(NODE_BY_ID['cdp-cyclotron-worker-email']), left(NODE_BY_ID.ses)) },
    {
        id: 'janitor-pg',
        d: () => {
            const [x1, y1] = top(NODE_BY_ID['cdp-cyclotron-v2-janitor'])
            const [x2, y2] = bottom(NODE_BY_ID.postgres)
            return `M${x1},${y1} L${x2},${y2}`
        },
    },
    {
        id: 'ses-feedback',
        d: () => {
            const [x1, y1] = bottom(NODE_BY_ID.ses)
            const [x2, y2] = bottom(NODE_BY_ID['cdp-api'])
            return `M${x1},${y1} C${x1},${y1 + 110} ${x2},${y2 + 110} ${x2},${y2}`
        },
    },
    {
        id: 'api-feedback',
        d: () =>
            curve(
                [NODE_BY_ID['cdp-api'].x + NODE_W, NODE_BY_ID['cdp-api'].y + 66],
                left(NODE_BY_ID['cdp-ses-webhooks'])
            ),
    },
]

function deliveryPath() {
    const svg = s('svg', { viewBox: '0 18 1312 470', class: 'path', role: 'img', 'aria-label': 'Delivery path' })
    const links = {}
    for (const link of LINKS) {
        const d = link.d()
        svg.append(s('path', { d, class: 'link' }))
        const flow = s('path', { d, class: 'flow' })
        svg.append(flow)
        links[link.id] = flow
    }
    const nodes = {}
    for (const node of NODES) {
        const state = s('text', { x: node.x + 12, y: node.y - 8, class: 'state' })
        const metric1 = s('text', { x: node.x + 12, y: node.y + 56, class: 'metric' })
        const metric2 = s('text', { x: node.x + 12, y: node.y + 72, class: 'metric' })
        const group = s(
            'g',
            { class: 'node' },
            s('rect', { x: node.x, y: node.y, width: NODE_W, height: NODE_H }),
            s('text', { x: node.x + 12, y: node.y + 22, class: 'name' }, node.name),
            s('text', { x: node.x + 12, y: node.y + 38, class: 'role' }, node.role),
            metric1,
            metric2,
            state
        )
        svg.append(group)
        nodes[node.id] = { group, state, metric1, metric2 }
    }
    const paint = (view) => {
        for (const node of NODES) {
            const { group, state, metric1, metric2 } = nodes[node.id]
            const nodeView = view.nodes[node.id] ?? {}
            group.setAttribute('class', `node ${nodeView.className ?? ''}`)
            state.textContent = nodeView.state ?? ''
            metric1.textContent = nodeView.lines?.[0] ?? ''
            metric2.textContent = nodeView.lines?.[1] ?? ''
        }
        for (const [id, flow] of Object.entries(links)) {
            const linkView = view.links?.[id]
            const rate = linkView?.rate ?? 0
            flow.classList.toggle('on', rate > 0)
            flow.classList.toggle('bad', Boolean(linkView?.bad))
            const speed = Math.max(0.25, Math.min(2.4, 2.4 / Math.sqrt(Math.max(rate, 0.1))))
            flow.style.setProperty('--speed', `${speed.toFixed(2)}s`)
        }
    }
    return { svg, paint }
}

// ---------- state at a moment of a run ----------

const atOrBefore = (points, t) => {
    let found
    for (const point of points) {
        if (point.at > t) {
            break
        }
        found = point
    }
    return found
}

const KILL_SHOWN_MS = 4000

function valveWindows(detail, cardView) {
    const driveEnd = detail.drive?.endedAt ?? Date.parse(detail.endedAt)
    const cardValves = cardView?.valves ?? []
    return (detail.scorecard.timeline ?? []).map((entry, i) => {
        const cardEntry = cardValves[i]?.valve === entry.valve ? cardValves[i] : undefined
        const from = entry.appliedAt ? Date.parse(entry.appliedAt) : null
        let to = entry.releasedAt ? Date.parse(entry.releasedAt) : from === null ? null : driveEnd
        if (entry.valve === 'role.kill' && from !== null) {
            to = from + KILL_SHOWN_MS
        }
        return { ...entry, from, to, dose: cardEntry?.dose ?? {} }
    })
}

function valveState(window) {
    const dose = window.dose ?? {}
    switch (window.valve) {
        case 'role.kill':
            return { className: 'killed', state: 'KILLED' }
        case 'role.freeze':
            return { className: 'frozen', state: 'FROZEN (SIGSTOP)' }
        case 'pg.drop_connections':
            return { className: 'faulted', state: `CONNECTIONS DROPPED${dose.share ? ` (${dose.share * 100}%)` : ''}` }
        case 'pg.failover':
            return { className: 'faulted', state: 'FAILING OVER' }
        case 'ses.throttle':
            return { className: 'faulted', state: `THROTTLED ${dose.rate ?? ''}/s` }
        case 'ses.reject':
            return { className: 'faulted', state: `REJECTING ${dose.type ?? ''}`.trim() }
        case 'dest.status':
            return {
                className: 'faulted',
                state: `ANSWERING ${dose.code ?? 'errors'}${dose.share ? ` to ${dose.share * 100}%` : ''}${dose.count ? ` x${dose.count}` : ''}`,
            }
        default:
            return { className: 'faulted', state: window.valve.toUpperCase() }
    }
}

function viewAt(detail, windows, t) {
    const perSecond = 1000 / detail.series.bucketMs
    const flow = atOrBefore(detail.series.flow, t) ?? {}
    const rate = (key) => (flow[key] ?? 0) * perSecond
    const nodes = {}
    const roleRate = {}
    for (const series of detail.series.roles) {
        const point = atOrBefore(series.points, t) ?? series.points[0]
        const fresh = point && Math.abs(t - point.at) <= detail.series.bucketMs * 3
        roleRate[series.role] = fresh ? point.processedPerSecond : 0
        nodes[series.role] = {
            lines: fresh
                ? [
                      `CPU ${fmtNumber(point.cpuPercent, 0)}%  ${fmtNumber(point.rssMb, 0)} MB`,
                      point.processedPerSecond > 0 ? `${fmtNumber(point.processedPerSecond)} processed/s` : '',
                  ]
                : ['not answering scrapes'],
        }
    }
    const queue = atOrBefore(detail.series.queue, t)
    const writer = atOrBefore(detail.series.writer, t)
    nodes.postgres = {
        lines: [
            queue ? `due ${queue.due}, running ${queue.running}` : '',
            [
                queue && queue.oldestDueSeconds > 0 ? `oldest ${fmtNumber(queue.oldestDueSeconds)}s` : '',
                writer ? `write ${fmtNumber(writer.latencyMs, 0)} ms` : '',
            ]
                .filter(Boolean)
                .join(', '),
        ],
    }
    if (writer && !writer.ok) {
        nodes.postgres.className = 'down'
        nodes.postgres.state = 'WRITES FAILING'
    } else if (queue && (queue.oldestDueSeconds > 5 || queue.due > 50)) {
        nodes.postgres.className = 'busy'
        nodes.postgres.state = 'BACKING UP'
    }
    const events = rate('offeredEvents')
    const transactional = rate('offeredTransactional')
    nodes.generator = {
        lines: [`${fmtNumber(events)} events/s`, `${fmtNumber(transactional)} API sends/s`],
    }
    nodes.kafka = { lines: [`${fmtNumber(events)} events/s in`] }
    nodes.hooks = {
        lines: [`${fmtNumber(rate('webhookOk'))}/s delivered`, `${fmtNumber(rate('webhookFaulted'))}/s failed`],
    }
    nodes.ses = { lines: [`${fmtNumber(rate('emailOk'))}/s sent`, `${fmtNumber(rate('emailFaulted'))}/s refused`] }
    nodes['cdp-ses-webhooks'] = {
        ...nodes['cdp-ses-webhooks'],
        lines: [nodes['cdp-ses-webhooks']?.lines?.[0] ?? '', flow.feedback ? `${flow.feedback} feedback` : ''],
    }
    for (const window of windows) {
        if (window.from === null || t < window.from || t >= window.to) {
            continue
        }
        const id = nodeOfTarget(window.target)
        if (id) {
            nodes[id] = { ...nodes[id], ...valveState(window) }
        }
    }
    for (const series of detail.series.roles) {
        const restarted = series.restarts.find((at) => t >= at && t < at + KILL_SHOWN_MS)
        if (restarted && nodes[series.role]?.className !== 'killed') {
            nodes[series.role] = { ...nodes[series.role], className: 'busy', state: 'RESTARTED' }
        }
    }
    const stopped = (role) => ['frozen', 'killed'].includes(nodes[role]?.className)
    const links = {
        'gen-kafka': { rate: events },
        'gen-api': { rate: transactional },
        'kafka-events': { rate: stopped('cdp-processed-events') ? 0 : events },
        'events-pg': { rate: roleRate['cdp-processed-events'] ?? 0 },
        'api-pg': { rate: stopped('cdp-api') ? 0 : transactional },
        'pg-hogflow': {
            rate: stopped('cdp-cyclotron-worker-hogflow') ? 0 : (roleRate['cdp-cyclotron-worker-hogflow'] ?? 0),
        },
        'pg-email': { rate: stopped('cdp-cyclotron-worker-email') ? 0 : (roleRate['cdp-cyclotron-worker-email'] ?? 0) },
        'hogflow-hooks': {
            rate: rate('webhookOk') + rate('webhookFaulted'),
            bad: rate('webhookFaulted') > rate('webhookOk'),
        },
        'email-ses': { rate: rate('emailOk') + rate('emailFaulted'), bad: rate('emailFaulted') > rate('emailOk') },
        'janitor-pg': { rate: roleRate['cdp-cyclotron-v2-janitor'] ?? 0 },
        'ses-feedback': { rate: rate('feedback') },
        'api-feedback': { rate: rate('feedback') },
    }
    return { nodes, links }
}

// ---------- charts ----------

function lineChart({ title, unit, series, from, to, bands = [], height = 220 }) {
    const width = 640
    const pad = { l: 48, r: 26, t: 10, b: 26 }
    const all = series.flatMap(({ points }) => points.map(([, v]) => v)).filter((v) => v !== null)
    const container = h('div', { class: 'panel chart' }, h('h3', {}, `${title}${unit ? ` (${unit})` : ''}`))
    if (all.length === 0 || to <= from) {
        container.append(h('div', { class: 'empty' }, 'No samples in this run'))
        return { el: container, cursor: () => undefined }
    }
    const legend = h('div', { class: 'legend' })
    for (const line of series) {
        legend.append(h('span', { style: `--swatch:${line.color}` }, line.name))
    }
    if (bands.length) {
        legend.append(h('span', { class: 'band', style: '--swatch:var(--series-2)' }, 'valve applied'))
    }
    if (series.length > 1 || bands.length) {
        container.append(legend)
    }
    const max = Math.max(...all, 0) * 1.1 || 1
    const x = (t) => pad.l + ((t - from) / (to - from)) * (width - pad.l - pad.r)
    const y = (v) => pad.t + (1 - v / max) * (height - pad.t - pad.b)
    const svg = s('svg', { viewBox: `0 0 ${width} ${height}` })
    for (const band of bands) {
        if (band.from === null) {
            continue
        }
        const x1 = x(Math.max(band.from, from))
        const x2 = x(Math.min(Math.max(band.to, band.from + 1000), to))
        svg.append(
            s('rect', {
                x: x1,
                y: pad.t,
                width: Math.max(x2 - x1, 2),
                height: height - pad.t - pad.b,
                fill: 'var(--series-2)',
                opacity: 0.16,
            })
        )
    }
    const ticks = 4
    for (let i = 0; i <= ticks; i++) {
        const v = (max / 1.1) * (i / ticks)
        svg.append(s('line', { x1: pad.l, x2: width - pad.r, y1: y(v), y2: y(v), stroke: 'var(--grid)' }))
        svg.append(
            s(
                'text',
                { x: pad.l - 6, y: y(v) + 4, 'text-anchor': 'end', fill: 'var(--muted)', 'font-size': 11 },
                fmtNumber(v)
            )
        )
    }
    const span = to - from
    const step = [10, 30, 60, 120, 300, 600, 1800].map((x) => x * 1000).find((x) => span / x <= 8) ?? 3600_000
    for (let t = 0; t <= span; t += step) {
        svg.append(
            s(
                'text',
                { x: x(from + t), y: height - 8, 'text-anchor': 'middle', fill: 'var(--muted)', 'font-size': 11 },
                fmtDuration(t)
            )
        )
    }
    svg.append(s('line', { x1: pad.l, x2: width - pad.r, y1: y(0), y2: y(0), stroke: 'var(--axis)' }))
    for (const line of series) {
        const pts = line.points.filter(([t, v]) => v !== null && t >= from - 5000 && t <= to + 5000)
        if (pts.length === 0) {
            continue
        }
        svg.append(
            s('path', {
                d: pts.map(([t, v], i) => `${i ? 'L' : 'M'}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(' '),
                fill: 'none',
                stroke: line.color,
                'stroke-width': 2,
                'stroke-linejoin': 'round',
            })
        )
        for (const [t, v] of line.marks ?? []) {
            svg.append(s('circle', { cx: x(t), cy: y(v), r: 4, fill: 'var(--critical)' }))
        }
    }
    const cursorLine = s('line', {
        y1: pad.t,
        y2: height - pad.b,
        stroke: 'var(--ink-2)',
        'stroke-width': 1,
        'stroke-dasharray': '3 3',
        visibility: 'hidden',
    })
    svg.append(cursorLine)
    const hit = s('rect', {
        x: pad.l,
        y: pad.t,
        width: width - pad.l - pad.r,
        height: height - pad.t - pad.b,
        fill: 'transparent',
    })
    hit.addEventListener('mousemove', (event) => {
        const box = svg.getBoundingClientRect()
        const px = ((event.clientX - box.left) / box.width) * width
        const t = from + ((px - pad.l) / (width - pad.l - pad.r)) * (to - from)
        cursorLine.setAttribute('x1', px)
        cursorLine.setAttribute('x2', px)
        cursorLine.setAttribute('visibility', 'visible')
        const rows = series
            .map((line) => {
                const point = atOrBefore(
                    line.points.map(([at, value]) => ({ at, value })),
                    t
                )
                return point
                    ? `<div class="r"><span><i style="--swatch:${line.color}"></i>${line.name}</span><b>${fmtNumber(point.value)}</b></div>`
                    : ''
            })
            .join('')
        showTooltip(event, `<div class="t">t+${fmtDuration(Math.max(t - from, 0))}</div>${rows}`)
    })
    hit.addEventListener('mouseleave', () => {
        hideTooltip()
        cursorLine.setAttribute('visibility', 'hidden')
    })
    svg.append(hit)
    container.append(svg)
    const replayLine = s('line', {
        y1: pad.t,
        y2: height - pad.b,
        stroke: 'var(--ink)',
        'stroke-width': 1.5,
        visibility: 'hidden',
    })
    svg.insertBefore(replayLine, hit)
    return {
        el: container,
        cursor: (t) => {
            if (t === null) {
                replayLine.setAttribute('visibility', 'hidden')
                return
            }
            replayLine.setAttribute('x1', x(t))
            replayLine.setAttribute('x2', x(t))
            replayLine.setAttribute('visibility', 'visible')
        },
    }
}

// ---------- pages ----------

let cardsCache
const cards = async () => (cardsCache ??= await getJson('/api/cards'))

function cardTile(card, runs) {
    const ofCard = runs.filter((run) => run.cardId === card.id)
    const last = ofCard[0]
    return h(
        'a',
        { class: 'panel card-tile', href: `#/cards/${card.id}` },
        h(
            'div',
            { class: 'title' },
            card.id,
            h('span', { class: 'badge' }, `v${card.version ?? '?'}`),
            card.runHostOnly ? h('span', { class: 'badge' }, 'run host only') : null,
            h('span', { style: 'flex:1' }),
            h('span', { class: 'status running live-badge', 'data-card': card.id, hidden: 'hidden' }, 'running now'),
            last ? statusPill(last.status) : h('span', { class: 'muted' }, 'never run')
        ),
        card.problems.length
            ? h('div', { class: 'reason failed' }, card.problems.join('; '))
            : [
                  h(
                      'div',
                      { class: 'row' },
                      h('span', { class: 'label' }, 'Found'),
                      h(
                          'div',
                          { class: 'finding', 'data-finding': card.id },
                          last
                              ? h('span', { class: 'muted' }, 'reading the last run…')
                              : h('span', { class: 'muted' }, '-')
                      )
                  ),
                  h(
                      'div',
                      { class: 'row' },
                      h('span', { class: 'label' }, 'Injects'),
                      card.valves.length
                          ? h(
                                'div',
                                { class: 'chips' },
                                card.valves.map((valve) =>
                                    h(
                                        'span',
                                        { class: 'chip valve', title: valveText(valve) },
                                        valvePlain(valve),
                                        h('span', { class: 'tech' }, `${valve.valve} → ${valve.target}`)
                                    )
                                )
                            )
                          : h(
                                'span',
                                { class: 'muted' },
                                card.steps.length > 1
                                    ? 'no valve: the load ramps until a bar breaks'
                                    : 'nothing: a baseline'
                            )
                  ),
                  h(
                      'div',
                      { class: 'row' },
                      h('span', { class: 'label' }, 'Load'),
                      h(
                          'div',
                          { class: 'chips' },
                          card.traffic.map((traffic) => h('span', { class: 'chip' }, trafficText(traffic))),
                          h('span', { class: 'chip' }, `for ${fmtDuration(card.driveMs)}`),
                          card.steps.length > 1
                              ? h(
                                    'span',
                                    { class: 'chip' },
                                    `ramp ${card.steps.map(({ scale }) => `${scale}x`).join(' → ')}`
                                )
                              : null
                      )
                  ),
                  h(
                      'div',
                      { class: 'row' },
                      h('span', { class: 'label' }, 'Judged by'),
                      h(
                          'div',
                          { class: 'chips' },
                          card.invariants.map(({ name, gate }) =>
                              h('span', { class: 'chip', title: name }, invariantPlain(name, gate))
                          ),
                          card.bars.map(({ name, params }) =>
                              h(
                                  'span',
                                  { class: 'chip' },
                                  `${name} ${params.percent ?? params.seconds ?? ''}${params.percent ? '%' : 's'}`
                              )
                          )
                      )
                  ),
                  h(
                      'div',
                      { class: 'row' },
                      h('span', { class: 'label' }, 'History'),
                      ofCard.length
                          ? h(
                                'div',
                                { class: 'dots' },
                                ofCard
                                    .slice(0, 20)
                                    .reverse()
                                    .map((run) =>
                                        h('span', {
                                            class: `dot ${run.status}`,
                                            title: `${run.status}, ${fmtTime(run.startedAt)}`,
                                        })
                                    )
                            )
                          : h('span', { class: 'muted' }, 'no runs on this box yet'),
                      last ? h('span', { class: 'muted', style: 'margin-left:8px' }, ago(last.startedAt)) : null
                  ),
              ]
    )
}

const PHASE_PLAIN = {
    reset: 'resetting the services',
    seed: 'creating test workflows',
    drive: 'sending load',
    converge: 'waiting for the last deliveries',
    judge: 'checking what arrived',
}

function findingOf(detail) {
    const perSecond = 1000 / detail.series.bucketMs
    const lines = []
    if (detail.status === 'passed') {
        lines.push('Every check held.')
    } else if (detail.status === 'failed') {
        const broke = detail.invariants.filter((i) => !i.passed).map((i) => invariantPlain(i.name))
        lines.push(broke.length ? `Broke: ${broke.join(', ')}.` : detail.statusReason)
    } else {
        lines.push(`Did not finish: ${detail.statusReason}`)
    }
    const p95 = latencyOf(detail, 'p95')
    if (p95 !== null) {
        lines.push(`95% of messages arrived within ${fmtNumber(p95 / 1000)} s.`)
    }
    const failing = Math.max(0, ...detail.series.flow.map((p) => (p.emailFaulted + p.webhookFaulted) * perSecond))
    if (failing >= 1) {
        const attempts = fmtNumber(failing, 0)
        lines.push(
            `Up to ${attempts} failed send ${attempts === '1' ? 'attempt' : 'attempts'} a second while the fault was on.`
        )
    }
    for (const role of detail.series.roles.filter((r) => r.restarts.length)) {
        lines.push(`The ${plainOf(role.role)} came back after a restart.`)
    }
    const due = Math.max(0, ...detail.series.queue.map((p) => p.due))
    if (due >= 20) {
        const oldest = Math.max(0, ...detail.series.queue.map((p) => p.oldestDueSeconds))
        lines.push(`Up to ${due} jobs waited in the job queue, the oldest for ${fmtNumber(oldest, 0)} s.`)
    }
    return lines.slice(0, 3)
}

async function cardsPage() {
    const [all, runs] = await Promise.all([cards(), getJson('/api/runs')])
    const running = h('div', { class: 'panel running-now' }, h('span', { class: 'muted' }, 'Checking for a run…'))
    const diagram = deliveryPath()
    diagram.paint({ nodes: {}, links: {} })
    render(
        h('h1', {}, 'Scenario dashboard'),
        h(
            'p',
            { class: 'sub' },
            `Each card breaks one part of the Workflows delivery path on purpose while synthetic load runs through it, then checks that every message still arrived. ${all.length} cards, ${runs.length} ${runs.length === 1 ? 'run' : 'runs'} on this box.`
        ),
        running,
        h(
            'div',
            { class: 'grid' },
            all.map((card) => cardTile(card, runs))
        ),
        h('h2', {}, 'The delivery path the cards break'),
        h(
            'div',
            { class: 'panel' },
            h(
                'p',
                { class: 'sub' },
                'An event or an API call starts a workflow. Its steps wait as jobs in the job queue database until a worker picks them up and sends the email or webhook.'
            ),
            diagram.svg
        )
    )
    const showLive = async () => {
        let live
        try {
            live = await getJson('/api/live')
        } catch (error) {
            running.replaceChildren(
                h('span', { class: 'muted' }, `The viewer cannot read the live run: ${error.message}`)
            )
            return
        }
        const now = live?.inProgress ? live : null
        document.querySelectorAll('.live-badge').forEach((badge) => (badge.hidden = badge.dataset.card !== now?.cardId))
        running.replaceChildren(
            ...(now
                ? [
                      statusPill('running'),
                      h('span', {}, ` ${now.cardId}, ${PHASE_PLAIN[now.phase] ?? now.phase}`),
                      h('a', { href: '#/live', class: 'open' }, 'Watch it live →'),
                  ]
                : [
                      h('span', { class: 'muted' }, 'Nothing running now.'),
                      runs[0]
                          ? h(
                                'span',
                                { class: 'muted' },
                                ` Last run: ${runs[0].cardId}, ${runs[0].status}, ${ago(runs[0].startedAt)}.`
                            )
                          : null,
                  ].filter(Boolean))
        )
    }
    const timer = setInterval(() => void showLive(), 2000)
    stopReplay = () => clearInterval(timer)
    await showLive()
    await Promise.all(
        all.map(async (card) => {
            const last = runs.find((run) => run.cardId === card.id)
            const slot = document.querySelector(`[data-finding="${card.id}"]`)
            if (!last || !slot) {
                return
            }
            try {
                const detail = await getJson(`/api/runs/${last.runId}`)
                slot.replaceChildren(...findingOf(detail).map((line) => h('div', {}, line)))
            } catch (error) {
                slot.replaceChildren(h('span', { class: 'muted' }, `Its last run did not load: ${error.message}`))
            }
        })
    )
}

function runsTable(runs) {
    if (runs.length === 0) {
        return h(
            'div',
            { class: 'panel muted' },
            'No runs yet. Run a card with: pnpm --dir nodejs exec tsx tests/scenarios/main.ts run smoke'
        )
    }
    return h(
        'div',
        { class: 'panel', style: 'padding:0' },
        h(
            'table',
            {},
            h(
                'thead',
                {},
                h(
                    'tr',
                    {},
                    h('th', {}, 'Status'),
                    h('th', {}, 'Card'),
                    h('th', {}, 'Started'),
                    h('th', { class: 'num' }, 'Duration'),
                    h('th', { class: 'num' }, 'Units offered'),
                    h('th', {}, 'Invariants'),
                    h('th', {}, 'Reason')
                )
            ),
            h(
                'tbody',
                {},
                runs.map((run) =>
                    h(
                        'tr',
                        { class: 'link', onclick: () => (location.hash = `#/runs/${run.runId}`) },
                        h('td', {}, statusPill(run.status)),
                        h('td', {}, run.cardId),
                        h('td', {}, fmtTime(run.startedAt)),
                        h('td', { class: 'num' }, fmtDuration(run.durationS * 1000)),
                        h(
                            'td',
                            { class: 'num' },
                            run.units ? `${run.units.offeredUnits} / ${run.units.targetUnits}` : '-'
                        ),
                        h(
                            'td',
                            {},
                            h(
                                'div',
                                { class: 'dots' },
                                run.invariants.map((inv) =>
                                    h('span', {
                                        class: `dot ${inv.passed ? 'passed' : 'failed'}`,
                                        title: `${inv.name}: ${inv.passed ? 'held' : 'broke'}`,
                                    })
                                )
                            )
                        ),
                        h('td', { class: 'muted', style: 'max-width:420px' }, run.statusReason)
                    )
                )
            )
        )
    )
}

async function runsPage() {
    const runs = await getJson('/api/runs')
    render(h('h1', {}, 'Runs'), h('p', { class: 'sub' }, 'Every run on this box, newest first.'), runsTable(runs))
}

const latencyOf = (run, key) =>
    run.measurements.find((m) => m.name === 'delivery_latency_ms' && m.key === key)?.value ?? null

async function cardPage(id) {
    const [all, runs] = await Promise.all([cards(), getJson('/api/runs')])
    const card = all.find((c) => c.id === id)
    if (!card) {
        render(h('h1', {}, 'No such card'))
        return
    }
    const ofCard = runs.filter((run) => run.cardId === id)
    const diagram = deliveryPath()
    const nodes = {}
    for (const valve of card.valves ?? []) {
        const node = nodeOfTarget(valve.target)
        if (node) {
            nodes[node] = { className: 'target', state: `${valve.valve}` }
        }
    }
    diagram.paint({ nodes, links: {} })
    const chronological = [...ofCard].reverse()
    const history = lineChart({
        title: 'Delivery latency across runs',
        unit: 'ms',
        series: [
            {
                name: 'p50',
                color: SERIES[0],
                points: chronological.map((run) => [Date.parse(run.startedAt), latencyOf(run, 'p50')]),
            },
            {
                name: 'p95',
                color: SERIES[1],
                points: chronological.map((run) => [Date.parse(run.startedAt), latencyOf(run, 'p95')]),
            },
        ],
        from: chronological.length ? Date.parse(chronological[0].startedAt) : 0,
        to: chronological.length ? Date.parse(chronological.at(-1).startedAt) : 0,
    })
    render(
        h('a', { href: '#/cards' }, '← Cards'),
        h('h1', {}, card.id, ' ', h('span', { class: 'badge' }, `v${card.version}`)),
        h(
            'p',
            { class: 'sub' },
            `Profile ${card.profileName}, seed ${card.seed}, ${card.teams} team${card.teams === 1 ? '' : 's'}. Converges within ${fmtDuration(card.convergeWithinMs)}.`,
            card.runHostOnly ? ' Judges only on a run host: a local run is invalid by design.' : ''
        ),
        h('div', { class: 'panel' }, h('h3', {}, 'Where it breaks the delivery path'), diagram.svg),
        h(
            'div',
            { class: 'split', style: 'margin-top:16px' },
            h(
                'div',
                { class: 'panel' },
                h('h3', {}, 'Valves'),
                card.valves.length
                    ? h(
                          'ul',
                          {},
                          card.valves.map((valve) => h('li', {}, valveText(valve)))
                      )
                    : h('p', { class: 'muted' }, 'None: this card is a baseline.'),
                h('h3', {}, 'Load'),
                h(
                    'ul',
                    {},
                    card.traffic.map((traffic) => h('li', {}, trafficText(traffic))),
                    h('li', {}, `drive for ${fmtDuration(card.driveMs)}, at least ${card.minOffered * 100}% offered`),
                    card.steps.length > 1
                        ? h(
                              'li',
                              {},
                              `ramp: ${card.steps.map(({ scale, fromMs, toMs }) => `${scale}x for ${fmtDuration(toMs - fromMs)}`).join(', ')}`
                          )
                        : null
                )
            ),
            h(
                'div',
                { class: 'panel' },
                h('h3', {}, 'Invariants, which fail the run'),
                h(
                    'ul',
                    {},
                    card.invariants.map(({ name, gate }) =>
                        h('li', {}, invariantPlain(name, gate), h('span', { class: 'muted mono' }, ` ${name}`))
                    )
                ),
                card.bars.length
                    ? [
                          h('h3', {}, 'Bars, per ramp step'),
                          h(
                              'ul',
                              {},
                              card.bars.map(({ name, params }) => h('li', {}, `${name}: ${JSON.stringify(params)}`))
                          ),
                      ]
                    : null,
                h('h3', {}, 'Measurements, which never fail it'),
                h(
                    'ul',
                    {},
                    card.measure.map((name) => h('li', {}, name))
                )
            )
        ),
        h('h2', {}, 'Runs'),
        ofCard.length > 1 ? h('div', { style: 'margin-bottom:16px' }, history.el) : null,
        runsTable(ofCard)
    )
}

function invariantsTable(run) {
    if (run.invariants.length === 0) {
        return h('p', { class: 'muted' }, 'Not judged: the run stopped before the Judge ran.')
    }
    return h(
        'table',
        {},
        h(
            'thead',
            {},
            h(
                'tr',
                {},
                h('th', {}, 'Invariant'),
                h('th', {}, 'Verdict'),
                h('th', { class: 'num' }, 'Observed'),
                h('th', { class: 'num' }, 'Gate'),
                h('th', {}, 'First violation')
            )
        ),
        h(
            'tbody',
            {},
            run.invariants.map((inv) =>
                h(
                    'tr',
                    {},
                    h(
                        'td',
                        {},
                        invariantPlain(inv.name, inv.gate ?? null),
                        h('div', { class: 'muted mono' }, inv.name)
                    ),
                    h('td', {}, statusPill(inv.passed ? 'passed' : 'failed')),
                    h('td', { class: 'num' }, inv.observed),
                    h('td', { class: 'num' }, inv.gate ?? '-'),
                    h('td', { class: 'muted' }, inv.violation ?? '')
                )
            )
        )
    )
}

function measurementsTable(run) {
    if (run.measurements.length === 0) {
        return h('p', { class: 'muted' }, 'No measurements.')
    }
    const fmt = (m) =>
        m.value === null ? 'unread' : m.unit === 'bytes' ? fmtBytes(m.value) : `${fmtNumber(m.value)} ${m.unit}`
    return h(
        'table',
        {},
        h('thead', {}, h('tr', {}, h('th', {}, 'Measurement'), h('th', {}, 'Of'), h('th', { class: 'num' }, 'Value'))),
        h(
            'tbody',
            {},
            run.measurements.map((m) =>
                h(
                    'tr',
                    {},
                    h('td', {}, m.name),
                    h('td', { class: 'mono' }, m.key ?? ''),
                    h(
                        'td',
                        { class: 'num' },
                        fmt(m),
                        m.incomplete ? h('span', { class: 'muted' }, ' (incomplete)') : '',
                        m.censored ? h('span', { class: 'muted' }, ' (censored)') : ''
                    )
                )
            )
        )
    )
}

function barsTable(run) {
    if (run.bars.length === 0) {
        return null
    }
    return [
        h('h2', {}, 'Bars and breaking points'),
        h(
            'div',
            { class: 'panel', style: 'padding:0' },
            h(
                'table',
                {},
                h('thead', {}, h('tr', {}, h('th', {}, 'Bar'), h('th', {}, 'Verdict'), h('th', {}, 'Breaking point'))),
                h(
                    'tbody',
                    {},
                    run.bars.map((bar) =>
                        h(
                            'tr',
                            {},
                            h('td', {}, bar.name),
                            h(
                                'td',
                                {},
                                bar.unjudged ? statusPill('invalid') : statusPill(bar.passed ? 'passed' : 'failed')
                            ),
                            h(
                                'td',
                                { class: 'muted' },
                                bar.unjudged ??
                                    (bar.breakingPoint
                                        ? `broke at ${bar.breakingPoint.scale}x (${fmtNumber(bar.breakingPoint.offeredPerSecond)} units/s offered)${bar.breakingPoint.key ? ` on ${bar.breakingPoint.key}` : ''}: ${fmtNumber(bar.breakingPoint.value)} ${bar.unit}`
                                        : 'held at every step')
                            )
                        )
                    )
                )
            )
        ),
    ]
}

function timelineTable(windows, from) {
    if (windows.length === 0) {
        return h('p', { class: 'muted' }, 'No valves: a baseline run.')
    }
    const rel = (iso) => (iso ? `t+${fmtDuration(Date.parse(iso) - from)}` : '-')
    return h(
        'table',
        {},
        h(
            'thead',
            {},
            h(
                'tr',
                {},
                h('th', {}, 'Valve'),
                h('th', {}, 'Target'),
                h('th', {}, 'Requested'),
                h('th', {}, 'Applied'),
                h('th', {}, 'Observed'),
                h('th', {}, 'Released'),
                h('th', {}, 'Problem')
            )
        ),
        h(
            'tbody',
            {},
            windows.map((w) =>
                h(
                    'tr',
                    {},
                    h(
                        'td',
                        {},
                        w.valve,
                        doseText(w.valve, w.dose)
                            ? h('span', { class: 'muted' }, ` (${doseText(w.valve, w.dose)})`)
                            : ''
                    ),
                    h('td', {}, plainOf(w.target), h('div', { class: 'muted mono' }, w.target)),
                    h('td', {}, rel(w.requestedAt)),
                    h('td', {}, rel(w.appliedAt)),
                    h('td', {}, rel(w.observedAt)),
                    h('td', {}, rel(w.releasedAt)),
                    h('td', { class: 'muted' }, w.error ?? w.releaseError ?? '')
                )
            )
        )
    )
}

let stopReplay = () => undefined

function runCharts(detail, windows, from, to) {
    const perSecond = 1000 / detail.series.bucketMs
    const flow = detail.series.flow
    const bands = windows.filter((w) => w.from !== null).map((w) => ({ from: w.from, to: w.to }))
    const at = (p) => p.at + detail.series.bucketMs / 2
    const charts = [
        lineChart({
            title: 'Throughput',
            unit: 'per second',
            from,
            to,
            bands,
            series: [
                {
                    name: 'units offered',
                    color: SERIES[0],
                    points: flow.map((p) => [at(p), (p.offeredEvents + p.offeredTransactional) * perSecond]),
                },
                {
                    name: 'deliveries',
                    color: SERIES[2],
                    points: flow.map((p) => [at(p), (p.emailOk + p.webhookOk) * perSecond]),
                },
                {
                    name: 'failed attempts',
                    color: SERIES[1],
                    points: flow.map((p) => [at(p), (p.emailFaulted + p.webhookFaulted) * perSecond]),
                },
            ],
        }),
        lineChart({
            title: 'Jobs waiting in the job queue',
            unit: 'jobs',
            from,
            to,
            bands,
            series: [
                { name: 'due', color: SERIES[0], points: detail.series.queue.map((p) => [p.at, p.due]) },
                { name: 'running', color: SERIES[1], points: detail.series.queue.map((p) => [p.at, p.running]) },
            ],
        }),
        lineChart({
            title: 'Delivery latency and queue age',
            unit: 'seconds',
            from,
            to,
            bands,
            series: [
                {
                    name: 'p50 latency',
                    color: SERIES[0],
                    points: flow.map((p) => [at(p), p.latencyP50Ms === null ? null : p.latencyP50Ms / 1000]),
                },
                {
                    name: 'p95 latency',
                    color: SERIES[1],
                    points: flow.map((p) => [at(p), p.latencyP95Ms === null ? null : p.latencyP95Ms / 1000]),
                },
                {
                    name: 'oldest due job',
                    color: SERIES[2],
                    points: detail.series.queue.map((p) => [p.at, p.oldestDueSeconds]),
                },
            ],
        }),
        lineChart({
            title: 'CPU per service',
            unit: '% of one core',
            from,
            to,
            bands,
            series: detail.series.roles.map((role, i) => ({
                name: NODE_BY_ID[role.role]?.name ?? role.role,
                color: SERIES[i % SERIES.length],
                points: role.points.map((p) => [p.at, p.cpuPercent]),
            })),
        }),
        lineChart({
            title: 'Time to write a job to the job queue database',
            unit: 'ms per write',
            from,
            to,
            bands,
            series: [
                {
                    name: 'write latency',
                    color: SERIES[0],
                    points: detail.series.writer.map((p) => [p.at, p.latencyMs]),
                    marks: detail.series.writer.filter((p) => !p.ok).map((p) => [p.at, p.latencyMs]),
                },
            ],
        }),
    ]
    return charts
}

const happeningsOf = (windows, roles) =>
    windows
        .flatMap((w) => [
            w.from !== null ? { at: w.from, text: `Valve on: ${valvePlain(w).toLowerCase()} (${w.valve})` } : null,
            w.releasedAt && w.valve !== 'role.kill'
                ? { at: Date.parse(w.releasedAt), text: `Valve off: the ${plainOf(w.target)} is back to normal` }
                : null,
        ])
        .concat(roles.flatMap((r) => r.restarts.map((at) => ({ at, text: `The ${plainOf(r.role)} restarted` }))))
        .filter(Boolean)
        .sort((a, b) => a.at - b.at)

async function runPage(runId, startAtSeconds = 0) {
    stopReplay()
    const [detail, all] = await Promise.all([getJson(`/api/runs/${runId}`), cards()])
    const cardView = all.find((c) => c.id === detail.cardId)
    const windows = valveWindows(detail, cardView)
    const from = detail.drive?.startedAt ?? Date.parse(detail.startedAt)
    const lastSample = Math.max(
        ...detail.series.queue.map((p) => p.at),
        ...detail.series.flow.map((p) => p.at + detail.series.bucketMs),
        from + 1000
    )
    const to = Math.min(Math.max(lastSample, detail.drive?.endedAt ?? 0), Date.parse(detail.endedAt))
    const diagram = deliveryPath()
    const charts = runCharts(detail, windows, from, to)
    const slider = h('input', { type: 'range', min: from, max: to, step: 250, value: from })
    const clock = h('span', { class: 'clock' })
    const events = h('div', { class: 'events' })
    const playButton = h('button', {}, 'Play')
    const speedSelect = h(
        'select',
        {},
        [5, 10, 20, 50].map((x) => h('option', { value: x, selected: x === 10 ? 'selected' : null }, `${x}x`))
    )
    const happenings = happeningsOf(windows, detail.series.roles)
    const show = (t) => {
        diagram.paint(viewAt(detail, windows, t))
        const phase = detail.drive && t > detail.drive.endedAt ? 'converging' : 'driving'
        clock.textContent = `t+${fmtDuration(t - from)} of ${fmtDuration(to - from)}, ${phase}`
        charts.forEach((chart) => chart.cursor(t))
        events.replaceChildren(
            ...happenings
                .filter((e) => e.at <= t)
                .slice(-3)
                .map((e) =>
                    h('div', { class: `e${t - e.at < 3000 ? ' now' : ''}` }, `t+${fmtDuration(e.at - from)}  ${e.text}`)
                )
        )
    }
    let timer
    const pause = () => {
        clearInterval(timer)
        timer = undefined
        playButton.textContent = 'Play'
    }
    stopReplay = pause
    playButton.addEventListener('click', () => {
        if (timer) {
            return pause()
        }
        if (Number(slider.value) >= to) {
            slider.value = from
        }
        playButton.textContent = 'Pause'
        timer = setInterval(() => {
            const next = Math.min(Number(slider.value) + 200 * Number(speedSelect.value), to)
            slider.value = next
            show(next)
            if (next >= to) {
                pause()
            }
        }, 200)
    })
    slider.addEventListener('input', () => show(Number(slider.value)))
    const reason = detail.statusReason
    render(
        h('a', { href: `#/cards/${detail.cardId}` }, `← ${detail.cardId}`),
        h('h1', {}, detail.cardId, ' ', statusPill(detail.status)),
        h(
            'p',
            { class: 'sub mono' },
            `run ${detail.runId}, started ${fmtTime(detail.startedAt)}${detail.headSha ? `, commit ${detail.headSha.slice(0, 10)}${detail.headDirty ? ' with local edits' : ''}` : ''}`
        ),
        h('div', { class: `reason ${detail.status}` }, reason),
        h(
            'div',
            { class: 'facts' },
            [
                ['Units offered', detail.units ? `${detail.units.offeredUnits} / ${detail.units.targetUnits}` : '-'],
                ['Converged', detail.converged === null ? '-' : detail.converged ? 'yes' : 'no'],
                ['Unfinished jobs', detail.unfinishedJobs ?? '-'],
                [
                    'Invariants held',
                    detail.invariants.length
                        ? `${detail.invariants.filter((i) => i.passed).length} / ${detail.invariants.length}`
                        : '-',
                ],
                [
                    'p95 latency',
                    latencyOf(detail, 'p95') === null ? '-' : `${fmtNumber(latencyOf(detail, 'p95') / 1000)} s`,
                ],
                ['Duration', fmtDuration(detail.durationS * 1000)],
            ].map(([k, v]) => h('div', { class: 'fact' }, h('div', { class: 'k' }, k), h('div', { class: 'v' }, v)))
        ),
        h(
            'div',
            { class: 'panel' },
            h('h3', {}, 'Replay on the delivery path'),
            diagram.svg,
            h('div', { class: 'replay' }, playButton, speedSelect, slider, clock),
            events
        ),
        h('h2', {}, 'Over the run'),
        h(
            'div',
            { class: 'charts' },
            charts.map((chart) => chart.el)
        ),
        h('h2', {}, 'Valve timeline'),
        h('div', { class: 'panel', style: 'padding:0' }, timelineTable(windows, from)),
        h('h2', {}, 'Invariants'),
        h('div', { class: 'panel', style: 'padding:0' }, invariantsTable(detail)),
        barsTable(detail),
        h('h2', {}, 'Measurements'),
        h('div', { class: 'panel', style: 'padding:0' }, measurementsTable(detail))
    )
    const start = Math.min(from + startAtSeconds * 1000, to)
    slider.value = start
    show(start)
}

const LIVE_POLL_MS = 1000
const PHASES = [
    ['reset', 'Reset'],
    ['seed', 'Seed'],
    ['drive', 'Drive'],
    ['converge', 'Converge'],
    ['judge', 'Judge'],
    ['end', 'Done'],
]

const liveDetail = (live) => ({
    ...live,
    endedAt: new Date(live.now).toISOString(),
    drive: live.drive && { startedAt: live.drive.startedAt, endedAt: live.drive.endedAt ?? live.now },
    scorecard: { timeline: live.timeline },
})

async function livePage() {
    stopReplay()
    const all = await cards()
    const diagram = deliveryPath()
    const header = h('div')
    const clock = h('span', { class: 'clock' })
    const phases = h('div', { class: 'phases', 'aria-live': 'polite' })
    const events = h('div', { class: 'events', 'aria-live': 'polite' })
    const chartsEl = h('div', { class: 'charts' })
    const empty = h('div', { class: 'panel empty' })
    const showIdle = (last) =>
        empty.replaceChildren(
            h('h3', {}, 'No run in progress'),
            h(
                'p',
                {},
                'Start one on the box, and it shows here within a second: ',
                h('code', {}, 'pnpm --dir nodejs exec tsx tests/scenarios/main.ts run <card>')
            ),
            last?.hasScorecard
                ? h(
                      'p',
                      {},
                      h(
                          'a',
                          { href: `#/runs/${last.runId}` },
                          `Replay the last run: ${last.cardId}, ${last.ended?.status ?? 'stopped'}, ${ago(new Date(last.updatedAt).toISOString())} →`
                      )
                  )
                : null
        )
    showIdle(null)
    const body = h(
        'div',
        {},
        h(
            'div',
            { class: 'panel' },
            h('h3', {}, 'The delivery path now'),
            diagram.svg,
            h('div', { class: 'replay' }, phases, clock),
            events
        ),
        h('h2', {}, 'So far'),
        chartsEl
    )
    render(header, empty, body)
    body.hidden = true
    let shownRun
    let watched
    let busy = false
    const poll = async () => {
        if (busy) {
            return
        }
        busy = true
        try {
            const live = await getJson('/api/live')
            if (live?.inProgress) {
                watched = live.runId
            }
            if (!live || (!live.inProgress && watched !== live.runId)) {
                showIdle(live)
                empty.hidden = false
                body.hidden = true
                header.replaceChildren(h('h1', {}, 'Live'))
                return
            }
            empty.hidden = true
            body.hidden = false
            const lost = !live.inProgress && !live.ended
            const lastSeen = lost ? live.updatedAt : live.now
            const detail = liveDetail(live)
            const cardView = all.find((c) => c.id === live.cardId)
            const windows = valveWindows(detail, cardView)
            const from = live.drive?.startedAt ?? Date.parse(live.startedAt)
            const planned = live.drive ? live.drive.startedAt + live.drive.forMs : from
            const lastData = Math.max(
                from,
                ...live.series.queue.map((p) => p.at),
                ...live.series.flow.map((p) => p.at + live.series.bucketMs),
                ...live.series.roles.flatMap((r) => r.points.map((p) => p.at))
            )
            const t = live.ended ? lastData : lastSeen - live.series.bucketMs
            const to = live.ended ? Math.max(lastData, from + 1000) : Math.max(planned, t, from + 1000)
            const shown = `${live.runId}/${live.phase}/${live.hasScorecard}/${live.inProgress}`
            if (shownRun !== shown) {
                shownRun = shown
                header.replaceChildren(
                    ...[
                        h(
                            'h1',
                            {},
                            live.ended ? 'Just ended: ' : lost ? 'Stopped: ' : 'Live: ',
                            h('a', { href: `#/cards/${live.cardId}` }, live.cardId),
                            ' ',
                            statusPill(live.ended ? live.ended.status : lost ? 'stopped' : 'running')
                        ),
                        h('p', { class: 'sub mono' }, `run ${live.runId}, started ${fmtTime(live.startedAt)}`),
                        live.ended
                            ? h(
                                  'div',
                                  { class: `reason ${live.ended.status}` },
                                  live.ended.statusReason,
                                  live.hasScorecard
                                      ? h('a', { href: `#/runs/${live.runId}`, class: 'open' }, ' Open the scorecard →')
                                      : null
                              )
                            : lost
                              ? h(
                                    'div',
                                    { class: 'reason invalid' },
                                    `The runner stopped writing ${ago(new Date(live.updatedAt).toISOString())} without a verdict, so this run has no scorecard. Its process most likely died.`
                                )
                              : null,
                    ].filter(Boolean)
                )
                const reached = new Set(live.phases.map((p) => p.phase).concat(live.ended ? ['end'] : []))
                phases.replaceChildren(
                    ...PHASES.map(([id, label]) =>
                        h(
                            'span',
                            {
                                class: `phase${reached.has(id) ? ' done' : ''}${live.phase === id ? ' now' : ''}`,
                                'aria-current': live.phase === id ? 'step' : null,
                            },
                            label
                        )
                    )
                )
            }
            diagram.paint(viewAt(detail, windows, t))
            clock.textContent = live.drive
                ? `t+${fmtDuration(Math.max(0, (live.ended ? lastData : lastSeen) - from))}${live.drive.forMs ? ` of ${fmtDuration(live.drive.forMs)} drive` : ''}`
                : `started ${ago(live.startedAt)}`
            const happenings = happeningsOf(windows, live.series.roles)
                .concat(
                    live.phases.map((p) => ({
                        at: p.at,
                        text: PHASE_PLAIN[p.phase] ? `Started ${PHASE_PLAIN[p.phase]}` : `${p.phase} started`,
                    }))
                )
                .sort((a, b) => a.at - b.at)
            events.replaceChildren(
                ...happenings
                    .slice(-4)
                    .map((e) =>
                        h(
                            'div',
                            { class: `e${lastSeen - e.at < 5000 ? ' now' : ''}` },
                            `${e.at < from ? 'before drive' : `t+${fmtDuration(e.at - from)}`}  ${e.text}`
                        )
                    )
            )
            const charts = runCharts(detail, windows, from, to)
            charts.forEach((chart) => chart.cursor(t))
            chartsEl.replaceChildren(...charts.map((chart) => chart.el))
        } catch (error) {
            body.hidden = true
            shownRun = undefined
            header.replaceChildren(h('h1', {}, 'Live'))
            empty.hidden = false
            empty.textContent = `The viewer lost the live run: ${error.message}`
        } finally {
            busy = false
        }
    }
    const timer = setInterval(() => void poll(), LIVE_POLL_MS)
    stopReplay = () => clearInterval(timer)
    await poll()
}

// ---------- router ----------

async function route() {
    stopReplay()
    hideTooltip()
    const [path, query] = location.hash.split('?')
    const [, page, id] = path.split('/')
    const startAt = Number(new URLSearchParams(query ?? '').get('t') ?? 0)
    document
        .querySelectorAll('nav a')
        .forEach((a) =>
            a.classList.toggle(
                'active',
                a.dataset.nav === (page || 'cards') || (page === 'cards' && a.dataset.nav === 'cards')
            )
        )
    try {
        if (page === 'live') {
            await livePage()
        } else if (page === 'runs' && id) {
            await runPage(id, startAt)
        } else if (page === 'runs') {
            await runsPage()
        } else if (page === 'cards' && id) {
            await cardPage(id)
        } else {
            await cardsPage()
        }
    } catch (error) {
        render(h('h1', {}, 'Something went wrong'), h('div', { class: 'reason failed' }, error.message))
    }
}

window.addEventListener('hashchange', () => void route())
void route()
