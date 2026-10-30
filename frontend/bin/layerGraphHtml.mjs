// Renders check-layers.mjs results as one self-contained HTML page: a column per layer, a box per
// folder, and a line for each folder pair joined by an upward import.

const shortName = (file) => file.replace(/^frontend\/src\//, '')

function groupOf(file) {
    const parts = shortName(file).split('/')
    if (parts[0] === 'products') {
        return parts.slice(0, 2).join('/') + (parts.includes('generated') ? '/generated' : '')
    }
    if (parts[0] === 'lib' && parts.length > 3) {
        return parts.slice(0, 3).join('/')
    }
    if (parts.length > 2) {
        return parts.slice(0, 2).join('/')
    }
    return parts.length === 2 ? `${parts[0]}/*` : 'src/*'
}

function bytesSavedByCut(files, root, reachBytes, cutFrom, cutTo) {
    const seen = new Set([root])
    const queue = [root]
    let bytes = files[root]?.bytes ?? 0
    while (queue.length) {
        const file = queue.pop()
        for (const target of files[file]?.staticImports ?? []) {
            if ((file === cutFrom && target === cutTo) || seen.has(target)) {
                continue
            }
            seen.add(target)
            bytes += files[target]?.bytes ?? 0
            queue.push(target)
        }
    }
    return reachBytes - bytes
}

export function renderLayerGraphHtml({ files, shellRoot, shellReach, upward, layerOf, layers }) {
    const reachBytes = [...shellReach.keys()].reduce((sum, file) => sum + (files[file]?.bytes ?? 0), 0)
    const groups = {}
    for (const [file, { bytes }] of Object.entries(files)) {
        const layer = layerOf(file)
        const key = `${layer}|${groupOf(file)}`
        groups[key] ??= { key, layer, name: groupOf(file), bytes: 0, eagerBytes: 0, files: [] }
        const eager = shellReach.has(file)
        groups[key].bytes += bytes
        groups[key].eagerBytes += eager ? bytes : 0
        groups[key].files.push([shortName(file), bytes, eager ? 1 : 0])
    }
    const imports = upward.map((edge) => {
        const [from, to] = edge.split(' -> ')
        const eager = shellReach.has(from)
        return {
            from: shortName(from),
            to: shortName(to),
            fromGroup: `${layerOf(from)}|${groupOf(from)}`,
            toGroup: `${layerOf(to)}|${groupOf(to)}`,
            eager: eager ? 1 : 0,
            saved: eager ? bytesSavedByCut(files, shellRoot, reachBytes, from, to) : 0,
        }
    })
    const parents = {}
    for (const [file, parent] of shellReach) {
        if (parent) {
            parents[shortName(file)] = shortName(parent)
        }
    }
    const data = {
        layers,
        groups: Object.values(groups),
        imports,
        parents,
        reachBytes,
        generated: new Date().toISOString(),
    }
    return PAGE.replace('__DATA__', JSON.stringify(data).replace(/</g, '\\u003c'))
}

const PAGE = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Frontend layer graph</title>
<style>
.viz-root {
  color-scheme: light;
  --surface-1: #fcfcfb; --surface-2: #f2f1ee; --border: #dcdbd6;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #77766f;
  --layer-kernel: #2a78d6; --layer-query: #1baf7a; --layer-shell: #eda100; --layer-features: #4a3aa7;
  --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  .viz-root {
    color-scheme: dark;
    --surface-1: #1a1a19; --surface-2: #242423; --border: #3a3a38;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #9a998f;
    --layer-kernel: #3987e5; --layer-query: #199e70; --layer-shell: #c98500; --layer-features: #9085e9;
  }
}
* { box-sizing: border-box; }
body { margin: 0; font: 13px/1.4 system-ui, sans-serif; }
.viz-root { background: var(--surface-1); color: var(--text-primary); min-height: 100vh; display: flex; flex-direction: column; }
header { padding: 12px 16px; border-bottom: 1px solid var(--border); display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: center; }
header h1 { font-size: 16px; margin: 0; }
.stat { color: var(--text-secondary); }
.stat b { color: var(--text-primary); }
.controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-left: auto; }
input[type=search] { background: var(--surface-2); color: var(--text-primary); border: 1px solid var(--border); border-radius: 4px; padding: 4px 8px; min-width: 220px; }
button.tab { background: none; border: 1px solid var(--border); color: var(--text-secondary); border-radius: 4px; padding: 4px 10px; cursor: pointer; }
button.tab[aria-pressed=true] { color: var(--text-primary); background: var(--surface-2); }
main { flex: 1; display: flex; min-height: 0; }
#graph { flex: 1; overflow: auto; }
aside { width: 380px; flex-shrink: 0; border-left: 1px solid var(--border); overflow: auto; padding: 12px 16px; }
aside h2 { font-size: 15px; margin: 0 0 4px; word-break: break-all; }
aside h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); margin: 16px 0 6px; }
aside ol, aside ul { margin: 0; padding-left: 18px; }
aside li { margin: 2px 0; word-break: break-all; }
.muted { color: var(--text-muted); }
.legend { display: flex; gap: 12px; align-items: center; color: var(--text-secondary); }
.swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: -1px; }
.upline { display: inline-block; width: 18px; border-top: 2px dashed var(--critical); margin-right: 4px; vertical-align: 3px; }
svg text { fill: var(--text-primary); font-size: 11px; pointer-events: none; }
svg .column-label { font-size: 13px; font-weight: 600; }
svg .size { fill: var(--text-secondary); }
.node rect { stroke: var(--surface-1); stroke-width: 2px; cursor: pointer; rx: 4px; }
.node.dim { opacity: .2; }
.edge { fill: none; stroke: var(--critical); stroke-dasharray: 5 3; }
.edge.dim { opacity: .04; }
#tooltip { position: fixed; pointer-events: none; background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 6px 8px; display: none; max-width: 360px; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--border); vertical-align: top; word-break: break-all; }
th { color: var(--text-muted); font-weight: 600; cursor: pointer; position: sticky; top: 0; background: var(--surface-1); }
td.layers, th { white-space: nowrap; }
td.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
#table { flex: 1; overflow: auto; padding: 0 16px 16px; display: none; }
a { color: inherit; }
</style>
</head>
<body>
<div class="viz-root">
<header>
  <h1>Frontend layer graph</h1>
  <span class="stat" id="totals"></span>
  <span class="legend" id="legend"></span>
  <div class="controls">
    <label><input type="checkbox" id="eagerOnly" checked> Eager path of every logged-in page only</label>
    <input type="search" id="search" placeholder="Filter folders">
    <button class="tab" id="showGraph" aria-pressed="true">Graph</button>
    <button class="tab" id="showTable" aria-pressed="false">Table</button>
  </div>
</header>
<main>
  <div id="graph"></div>
  <div id="table"></div>
  <aside id="details"><p class="muted">Select a folder to see its upward imports, why it is eager, and its largest files. Sizes are source bytes, before minify.</p></aside>
</main>
<div id="tooltip"></div>
</div>
<script>
const DATA = __DATA__
const { layers, groups, imports, parents } = DATA
const kib = (bytes) => bytes >= 1048576 ? (bytes / 1048576).toFixed(2) + ' MiB' : Math.round(bytes / 1024) + ' KiB'
const byKey = Object.fromEntries(groups.map((g) => [g.key, g]))
const state = { eagerOnly: true, search: '', selected: null, sort: 'saved' }

const eagerImports = imports.filter((i) => i.eager)
document.getElementById('totals').innerHTML =
  '<b>' + imports.length + '</b> upward imports, <b>' + eagerImports.length + '</b> on the eager path. Eager path: <b>' + kib(DATA.reachBytes) + '</b> source.'
document.getElementById('legend').innerHTML =
  layers.map((l) => '<span><span class="swatch" style="background:var(--layer-' + l + ')"></span>' + l + '</span>').join('') +
  '<span><span class="upline"></span>upward import</span>'

function visibleGroups() {
  return groups.filter((g) => (!state.eagerOnly || g.eagerBytes > 0) && (!state.search || g.name.includes(state.search)))
}
function visibleImports() {
  return imports.filter((i) => !state.eagerOnly || i.eager)
}
const sizeOf = (g) => (state.eagerOnly ? g.eagerBytes : g.bytes)

function edgesBetweenGroups(list) {
  const edges = {}
  for (const i of list) {
    const key = i.fromGroup + '>' + i.toGroup
    edges[key] ??= { from: i.fromGroup, to: i.toGroup, count: 0, saved: 0 }
    edges[key].count++
    edges[key].saved = Math.max(edges[key].saved, i.saved)
  }
  return Object.values(edges)
}

function drawGraph() {
  const shown = visibleGroups()
  const maxBytes = Math.max(1, ...shown.map(sizeOf))
  const columnWidth = 220, gap = 80, top = 40, left = 16
  const positions = {}
  let height = 0
  layers.forEach((layer, column) => {
    let y = top
    for (const g of shown.filter((g) => g.layer === layer).sort((a, b) => sizeOf(b) - sizeOf(a))) {
      const h = 18 + Math.round(70 * Math.sqrt(sizeOf(g) / maxBytes))
      positions[g.key] = { x: left + column * (columnWidth + gap), y, h }
      y += h + 2
    }
    height = Math.max(height, y)
  })
  const width = left * 2 + layers.length * columnWidth + (layers.length - 1) * gap
  const edges = edgesBetweenGroups(visibleImports()).filter((e) => positions[e.from] && positions[e.to])
  const related = new Set()
  if (state.selected) {
    related.add(state.selected)
    for (const e of edges) if (e.from === state.selected || e.to === state.selected) { related.add(e.from); related.add(e.to) }
  }
  const maxSaved = Math.max(1, ...edges.map((e) => e.saved))
  let svg = '<svg width="' + width + '" height="' + (height + 20) + '" role="img" aria-label="Folders by layer, with upward imports">'
  layers.forEach((layer, column) => {
    svg += '<text class="column-label" x="' + (left + column * (columnWidth + gap)) + '" y="22">' + layer + '</text>'
  })
  for (const e of edges) {
    const a = positions[e.from], b = positions[e.to]
    const x1 = a.x + columnWidth, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2, mid = (x1 + x2) / 2
    const dim = state.selected && e.from !== state.selected && e.to !== state.selected
    const strokeWidth = 1 + (state.eagerOnly ? 3 * Math.sqrt(e.saved / maxSaved) : Math.min(3, e.count / 4))
    svg += '<path class="edge' + (dim ? ' dim' : '') + '" stroke-width="' + strokeWidth.toFixed(1) + '" opacity="0.55" d="M' + x1 + ',' + y1 + ' C' + mid + ',' + y1 + ' ' + mid + ',' + y2 + ' ' + x2 + ',' + y2 + '"/>'
  }
  for (const g of shown) {
    const p = positions[g.key]
    const dim = state.selected && !related.has(g.key)
    svg += '<g class="node' + (dim ? ' dim' : '') + '" data-key="' + g.key + '"><rect x="' + p.x + '" y="' + p.y + '" width="' + columnWidth + '" height="' + p.h + '" fill="var(--layer-' + g.layer + ')" fill-opacity="0.22"/>' +
      '<rect x="' + p.x + '" y="' + p.y + '" width="4" height="' + p.h + '" fill="var(--layer-' + g.layer + ')"/>' +
      '<text x="' + (p.x + 10) + '" y="' + (p.y + 13) + '">' + truncate(g.name, 26) + '</text>' +
      '<text class="size" x="' + (p.x + columnWidth - 6) + '" y="' + (p.y + 13) + '" text-anchor="end">' + kib(sizeOf(g)) + '</text></g>'
  }
  svg += '</svg>'
  const container = document.getElementById('graph')
  container.innerHTML = svg
  container.querySelectorAll('.node').forEach((node) => {
    const g = byKey[node.dataset.key]
    node.addEventListener('click', () => select(g.key))
    node.addEventListener('mousemove', (event) => showTooltip(event, '<b>' + g.name + '</b><br>' + g.layer + ' layer<br>' + kib(sizeOf(g)) + ' in ' + g.files.filter((f) => !state.eagerOnly || f[2]).length + ' files'))
    node.addEventListener('mouseleave', hideTooltip)
  })
}

function truncate(text, max) { return text.length > max ? '...' + text.slice(text.length - max + 3) : text }

function showTooltip(event, html) {
  const tip = document.getElementById('tooltip')
  tip.innerHTML = html
  tip.style.display = 'block'
  tip.style.left = event.clientX + 14 + 'px'
  tip.style.top = event.clientY + 14 + 'px'
}
function hideTooltip() { document.getElementById('tooltip').style.display = 'none' }

function chainTo(file) {
  const chain = []
  for (let f = file; f; f = parents[f]) chain.unshift(f)
  return chain
}

function select(key) {
  state.selected = state.selected === key ? null : key
  drawGraph()
  const details = document.getElementById('details')
  if (!state.selected) { details.innerHTML = '<p class="muted">Select a folder.</p>'; return }
  const g = byKey[key]
  const out = visibleImports().filter((i) => i.fromGroup === key).sort((a, b) => b.saved - a.saved)
  const into = visibleImports().filter((i) => i.toGroup === key).sort((a, b) => b.saved - a.saved)
  const eagerFiles = g.files.filter((f) => f[2]).sort((a, b) => b[1] - a[1])
  const list = (items, render) => items.length ? '<ul>' + items.map(render).join('') + '</ul>' : '<p class="muted">None.</p>'
  const importLine = (i) => '<li>' + i.from + ' <span class="muted">-></span> ' + i.to + (i.eager ? ' <span class="muted">(' + (i.saved ? 'cut saves ' + kib(i.saved) : 'other imports keep it eager') + ')</span>' : '') + '</li>'
  details.innerHTML =
    '<h2>' + g.name + '</h2><div class="muted">' + g.layer + ' layer, ' + kib(g.eagerBytes) + ' eager of ' + kib(g.bytes) + '</div>' +
    '<h3>Upward imports out (' + out.length + ')</h3>' + list(out, importLine) +
    '<h3>Upward imports in (' + into.length + ')</h3>' + list(into, importLine) +
    '<h3>Why it is eager</h3>' + (eagerFiles.length ? '<ol>' + chainTo(eagerFiles[0][0]).map((f) => '<li>' + f + '</li>').join('') + '</ol>' : '<p class="muted">Not on the eager path.</p>') +
    '<h3>Largest files</h3>' + list(g.files.slice().sort((a, b) => b[1] - a[1]).slice(0, 25), (f) => '<li>' + f[0] + ' <span class="muted">' + kib(f[1]) + (f[2] ? ', eager' : '') + '</span></li>')
}

function drawTable() {
  const rows = visibleImports().filter((i) => !state.search || i.from.includes(state.search) || i.to.includes(state.search))
  const key = state.sort
  rows.sort((a, b) => (key === 'saved' ? b.saved - a.saved : String(a[key]).localeCompare(String(b[key]))))
  const layer = (groupKey) => groupKey.split('|')[0]
  document.getElementById('table').innerHTML = '<table><thead><tr>' +
    [['from', 'From'], ['to', 'To'], ['fromGroup', 'Layers'], ['saved', 'Cut saves']].map(([k, label]) => '<th data-sort="' + k + '">' + label + '</th>').join('') +
    '</tr></thead><tbody>' + rows.map((i) => '<tr><td>' + i.from + '</td><td>' + i.to + '</td><td class="layers">' + layer(i.fromGroup) + ' -> ' + layer(i.toGroup) + '</td><td class="num">' + (i.eager ? kib(i.saved) : '-') + '</td></tr>').join('') + '</tbody></table>'
  document.querySelectorAll('#table th').forEach((th) => th.addEventListener('click', () => { state.sort = th.dataset.sort; drawTable() }))
}

function redraw() { drawGraph(); drawTable() }
document.getElementById('eagerOnly').addEventListener('change', (e) => { state.eagerOnly = e.target.checked; state.selected = null; redraw() })
document.getElementById('search').addEventListener('input', (e) => { state.search = e.target.value.trim(); redraw() })
function showView(table) {
  document.getElementById('graph').style.display = table ? 'none' : 'block'
  document.getElementById('table').style.display = table ? 'block' : 'none'
  document.getElementById('showGraph').setAttribute('aria-pressed', String(!table))
  document.getElementById('showTable').setAttribute('aria-pressed', String(table))
}
document.getElementById('showGraph').addEventListener('click', () => showView(false))
document.getElementById('showTable').addEventListener('click', () => showView(true))
redraw()
</script>
</body>
</html>
`
