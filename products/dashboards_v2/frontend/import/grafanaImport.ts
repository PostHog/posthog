import { MAX_QUERY_TEXT, type PanelQuery, panelQuerySchema } from '../dashboard/dashboardSchema'
import { type Dashboard, GRID, type GridTab, type Tile } from '../dashboard/dashboardTypes'
import type { ChartConfig } from '../panels/chart/chartSpec'
import type { StatOptions } from '../panels/chart/viz/stat/statSpec'
import { fromV2 } from './grafanaV2'
import {
    type ImportResult,
    type ImportedVariable,
    type ReportBuilder,
    type TileStatus,
    MAX_LEGEND,
    MAX_REF_ID,
    MAX_TARGETS,
    chartPanel,
    idMaker,
    importedTile,
    isBoardTime,
    notePanel,
    reportBuilder,
} from './importReport'
import {
    fillVariables,
    fixLogqlWindows,
    logqlLegend,
    logqlStreams,
    looksLikeLogql,
    metricsqlFunctions,
    promqlMetrics,
    rewriteLogql,
    stripStepWindows,
} from './promqlText'

/**
 * Grafana dashboard JSON, classic or Grafana 12's v2 schema, as a board. Ported from Dash's importer
 * (`importGrafana` in `packages/templates/src/grafana.ts`). It never throws on odd panels: a panel it can't run
 * becomes a note that says why and keeps the original queries, and the report lists every tile.
 */

type Json = any // eslint-disable-line @typescript-eslint/no-explicit-any

const VIZ: Record<string, { type: string; lossy?: string }> = {
    timeseries: { type: 'line' },
    graph: { type: 'line' },
    barchart: { type: 'bar' },
    stat: { type: 'stat' },
    singlestat: { type: 'stat' },
    gauge: { type: 'stat', lossy: 'There is no gauge chart yet, so it shows as a number.' },
    bargauge: { type: 'stat', lossy: 'There is no bar gauge yet, so it shows as a number.' },
    table: { type: 'bar', lossy: 'There is no table chart yet, so it shows as bars.' },
    'table-old': { type: 'bar', lossy: 'There is no table chart yet, so it shows as bars.' },
    piechart: { type: 'bar', lossy: 'There is no pie chart yet, so it shows as bars.' },
    histogram: { type: 'bar', lossy: 'There is no histogram yet, so it shows as bars.' },
    'state-timeline': { type: 'line', lossy: 'There is no state timeline yet, so it shows as lines.' },
    'status-history': { type: 'line', lossy: 'There is no status history yet, so it shows as lines.' },
    trend: { type: 'line', lossy: 'There is no trend chart yet, so it shows as lines.' },
    xychart: { type: 'line', lossy: 'There is no XY chart yet, so it shows as lines.' },
}

const PROMETHEUS = new Set([
    'prometheus',
    'victoriametrics',
    'victoriametrics-datasource',
    'victoriametrics-metrics-datasource',
])
const DATASOURCE_NAMES: Record<string, string> = {
    loki: 'Loki',
    'grafana-clickhouse-datasource': 'ClickHouse SQL',
    cloudwatch: 'CloudWatch',
    __expr__: 'Grafana expressions',
    'grafana-postgresql-datasource': 'Postgres SQL',
    'yesoreyeram-infinity-datasource': 'Infinity',
}

/**
 * Grafana rows are 30px with 8px gaps; ours are 10px with 12px gaps. Converting the edges rather than the heights keeps
 * tiles that touched in Grafana touching here.
 */
const GRAFANA_ROW_PX = 38
const toRows = (grafanaRows: number): number => Math.round((grafanaRows * GRAFANA_ROW_PX) / (GRID.rowPx + GRID.gapPx))

const int = (value: unknown, fallback: number): number =>
    Number.isFinite(Number(value)) ? Math.round(Number(value)) : fallback

function statFormat(unit: unknown): StatOptions['format'] | undefined {
    if (unit === 'percent' || unit === 'percentunit') {
        return 'percentage'
    }
    return typeof unit === 'string' && unit.startsWith('currency') ? 'currency' : undefined
}

const LATEST_REDUCERS = new Set(['last', 'lastNotNull'])

const LOGQL_WINDOW = '1m'

/**
 * Grafana's Prometheus and Loki escaping: a multi-value or All variable is a regex alternation, so each value's regex
 * characters are escaped; a single value is a plain string. Both escape for the quoted string they land in.
 */
const escapeString = (value: string): string => value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
const escapeRegex = (value: string): string => escapeString(value.replace(/[$^*{}[\]'+?.()|\\]/g, '\\$&'))

/** A variable's saved value, as text a query can hold. `All` becomes the variable's all value, or a match-all regex. */
function variableValue(variable: Json): string | undefined {
    const current = variable.current?.value
    const values = (Array.isArray(current) ? current : current === undefined || current === null ? [] : [current]).map(
        String
    )
    if (values.length === 0) {
        return typeof variable.query === 'string' && variable.type !== 'query'
            ? variable.query.split(',')[0]?.trim()
            : undefined
    }
    if (values.includes('$__all')) {
        return variable.allValue || '.*'
    }
    return variable.multi || variable.includeAll || values.length > 1
        ? values.map(escapeRegex).join('|')
        : escapeString(values[0])
}

const inline = (value: unknown): string =>
    String(value)
        .replace(/[`\r\n]+/g, ' ')
        .trim()

interface Converter {
    report: ReportBuilder
    variables: Map<string, string>
    nextId: (title: string) => string
    datasourceType: (datasource: unknown) => string | undefined
}

type ImportedTarget = { refId: string; query: PanelQuery; legend?: string }
type OriginalQuery = { language: string; text: string }

function tilePlace(gridPos: Json, top: number): Tile['place'] {
    const x = Math.min(23, Math.max(0, int(gridPos.x, 0)))
    const y = Math.max(0, int(gridPos.y, 0) - top)
    return {
        x,
        y: toRows(y),
        w: Math.min(24 - x, Math.max(1, int(gridPos.w, 12))),
        h: Math.max(1, toRows(y + Math.max(1, int(gridPos.h, 8))) - toRows(y)),
    }
}

function targetType(
    target: Json,
    expr: string | undefined,
    panelType: string | undefined,
    converter: Converter
): string | undefined {
    const type = converter.datasourceType(target.datasource) ?? (panelType === 'unknown' ? undefined : panelType)
    if (expr !== undefined && (type === undefined || type === 'unknown')) {
        return looksLikeLogql(expr) ? 'loki' : 'prometheus'
    }
    return type
}

/** The query text as the board runs it, with what it needs added to the report and what differs added to `reasons`. */
function telemetryText(
    expr: string,
    refId: string,
    loki: boolean,
    converter: Converter,
    reasons: string[]
): { text: string; filled: boolean } | undefined {
    let cleaned = expr.replace(/\$\{DS_[A-Z0-9_]+\}/g, '')
    if (loki) {
        const windows = fixLogqlWindows(cleaned, LOGQL_WINDOW)
        cleaned = windows.text
        if (windows.replaced) {
            reasons.push(`${refId} uses a ${LOGQL_WINDOW} window where Grafana picked one from the time range.`)
        }
    } else {
        cleaned = stripStepWindows(cleaned)
    }
    const filled = fillVariables(cleaned, converter.variables, MAX_QUERY_TEXT)
    if (filled.overflow) {
        return undefined
    }
    for (const name of filled.unfilled) {
        reasons.push(`$${name} has no saved value, so ${refId} keeps it as written and may not run.`)
    }
    if (loki) {
        logqlStreams(filled.text).forEach((stream) => converter.report.require('logStreams', rewriteLogql(stream)))
        return { text: rewriteLogql(filled.text), filled: filled.unfilled.length === 0 }
    }
    for (const name of metricsqlFunctions(filled.text)) {
        reasons.push(`${refId} uses the MetricsQL function ${name}(), which PostHog may not run.`)
    }
    promqlMetrics(filled.text)
        .filter((name) => !name.startsWith('$'))
        .forEach((name) => converter.report.require('metrics', name))
    return { text: filled.text, filled: filled.unfilled.length === 0 }
}

function telemetryTarget(
    expr: string,
    refId: string,
    legend: string | undefined,
    loki: boolean,
    scaleToFraction: boolean,
    converter: Converter,
    reasons: string[]
): ImportedTarget | OriginalQuery {
    const converted = telemetryText(expr, refId, loki, converter, reasons)
    const query: PanelQuery | undefined = converted && {
        language: loki ? 'logql' : 'promql',
        query: scaleToFraction ? `(${converted.text}) / 100` : converted.text,
    }
    if (!converted || !query || !panelQuerySchema.safeParse(query).success) {
        converter.report.query(false)
        reasons.push(`${refId} is too long for a board query once its variables are filled in.`)
        return { language: '', text: `-- ${refId}\n${expr}` }
    }
    let targetLegend = legend && loki ? logqlLegend(legend) : legend
    if (targetLegend && targetLegend.length > MAX_LEGEND) {
        reasons.push(`${refId}'s legend is too long, so it uses the default.`)
        targetLegend = undefined
    }
    converter.report.query(converted.filled)
    return { refId, query, legend: targetLegend }
}

function unrunnableQuery(
    target: Json,
    refId: string,
    type: string | undefined,
    converter: Converter,
    reasons: string[]
): OriginalQuery {
    const text =
        [target.rawSql, target.expr, target.expression, target.query, target.sqlExpression].find(
            (candidate) => typeof candidate === 'string' && candidate.trim()
        ) ?? ''
    const language = DATASOURCE_NAMES[type ?? ''] ?? type ?? 'an unknown datasource'
    converter.report.query(false)
    reasons.push(`${refId} queries ${language}, which PostHog can't run.`)
    return { language: /sql/i.test(language) ? 'sql' : '', text: `-- ${refId} · ${language}\n${text}` }
}

interface RefIds {
    used: Set<string>
    // The next suffix to try for each refId, so many targets sharing one don't rescan from 2.
    next: Map<string, number>
}

function uniqueRefId(refId: string, refIds: RefIds): string {
    let id = refId.slice(0, MAX_REF_ID)
    let n = refIds.next.get(refId) ?? 2
    while (refIds.used.has(id)) {
        id = `${refId.slice(0, MAX_REF_ID - String(n).length - 1)}-${n}`
        n++
    }
    refIds.next.set(refId, n)
    refIds.used.add(id)
    return id
}

function convertTargets(
    panel: Json,
    scaleToFraction: boolean,
    converter: Converter,
    reasons: string[]
): { targets: ImportedTarget[]; skipped: OriginalQuery[] } {
    const targets: ImportedTarget[] = []
    const skipped: OriginalQuery[] = []
    const panelType = converter.datasourceType(panel.datasource)
    const refIds: RefIds = { used: new Set(), next: new Map() }
    for (const [index, target] of (Array.isArray(panel.targets) ? panel.targets : []).entries()) {
        if (!target || typeof target !== 'object' || target.hide) {
            continue
        }
        const refId = uniqueRefId(String(target.refId ?? String.fromCharCode(65 + index)), refIds)
        const expr = typeof target.expr === 'string' ? target.expr : undefined
        if (expr !== undefined && !expr.trim()) {
            continue
        }
        const type = targetType(target, expr, panelType, converter)
        if (expr === undefined || !(PROMETHEUS.has(type ?? '') || type === 'loki')) {
            skipped.push(unrunnableQuery(target, refId, type, converter, reasons))
            continue
        }
        const legend = target.legendFormat && target.legendFormat !== '__auto' ? String(target.legendFormat) : undefined
        const converted = telemetryTarget(expr, refId, legend, type === 'loki', scaleToFraction, converter, reasons)
        if ('refId' in converted) {
            targets.push(converted)
        } else {
            skipped.push(converted)
        }
    }
    return { targets, skipped }
}

/** Grafana settings the chart can't reproduce, so the tile reads as partial. */
function droppedSettings(panel: Json, vizType: string): string[] {
    const reasons: string[] = []
    const transformations = Array.isArray(panel.transformations)
        ? panel.transformations.filter((t: Json) => t && !t.disabled)
        : []
    if (transformations.length) {
        const ids = [...new Set(transformations.map((t: Json) => String(t.id)))]
        reasons.push(`Grafana transformations (${ids.join(', ')}) aren't applied.`)
    }
    const calcs = panel.options?.reduceOptions?.calcs
    if (vizType === 'stat' && Array.isArray(calcs) && calcs.length && !LATEST_REDUCERS.has(String(calcs[0]))) {
        reasons.push(`It showed the ${calcs[0]} of each series in Grafana. Here it shows the latest value.`)
    }
    return reasons
}

function chartViz(panel: Json, vizType: string, unit: unknown): ChartConfig['viz'] {
    const format = vizType === 'stat' ? statFormat(unit) : undefined
    if (format) {
        return { type: 'stat', options: { format } }
    }
    return panel.fieldConfig?.defaults?.custom?.stacking?.mode === 'normal' && vizType === 'bar'
        ? { type: 'bar', options: { stack: true } }
        : { type: vizType }
}

function convertPanel(panel: Json, converter: Converter, top: number): Tile {
    const title = panel.title ? String(panel.title) : undefined
    const id = converter.nextId(title || panel.type || 'panel')
    const place = tilePlace(panel.gridPos ?? {}, top)
    const reasons: string[] = []
    const done = (content: Tile['panel'], status: TileStatus): Tile => {
        converter.report.tile({ tileId: id, title: title ?? '', from: String(panel.type ?? 'panel'), status, reasons })
        return importedTile(id, place, content)
    }

    if (panel.libraryPanel && !panel.type) {
        const name = panel.libraryPanel.name ?? panel.libraryPanel.uid
        reasons.push(`Library panel "${name}" isn't part of the export.`)
        return done(notePanel(title, `**Not supported yet:** library panel \`${inline(name)}\`.`, []), 'unsupported')
    }
    if (panel.type === 'text') {
        const text = String(panel.options?.content ?? panel.content ?? '')
        return done({ type: 'markdown', ...(title ? { title } : {}), config: { text } }, 'mapped')
    }

    const viz = VIZ[panel.type]
    const unit = panel.fieldConfig?.defaults?.unit ?? panel.format
    // Grafana's `percent` is already 0 to 100, but the stat's percentage format multiplies by 100.
    const scaleToFraction = viz?.type === 'stat' && unit === 'percent'
    const { targets, skipped } = convertTargets(panel, scaleToFraction, converter, reasons)

    if (!viz) {
        reasons.unshift(`Grafana panel type "${panel.type}" has no equivalent yet.`)
        const original = [
            ...targets.map((t) => ({ language: t.query.language, text: String(t.query.query) })),
            ...skipped,
        ]
        return done(notePanel(title, `**Not supported yet:** ${inline(panel.type)}`, original), 'unsupported')
    }
    if (targets.length === 0) {
        const heading = `**Not supported yet:** this ${inline(panel.type)} panel has no query PostHog can run.`
        return done(notePanel(title, heading, skipped), 'unsupported')
    }
    if (viz.lossy) {
        reasons.unshift(viz.lossy)
    }
    if (targets.length > MAX_TARGETS) {
        reasons.push(`Only the first ${MAX_TARGETS} of its ${targets.length} queries are kept.`)
        targets.length = MAX_TARGETS
    }
    reasons.push(...droppedSettings(panel, viz.type))
    const description = panel.description ? String(panel.description) : undefined
    const chart = chartPanel(title, description, targets, chartViz(panel, viz.type, unit))
    return done(chart, reasons.length ? 'partial' : 'mapped')
}

/**
 * Rows own the panels after them until the next row, or hold them in `panels` when collapsed. A row marked `__tab`
 * starts a new tab.
 */
function layoutPanels(panels: Json[], converter: Converter, firstTabTitle: string): GridTab[] {
    const tabs: GridTab[] = []
    const tabId = idMaker('tab')
    let tab: GridTab | undefined
    let section: { tile: Tile; top: number; tiles: Tile[] } | undefined
    const currentTab = (): GridTab => {
        if (!tab) {
            tab = { id: tabId(firstTabTitle), title: firstTabTitle, tiles: [] }
            tabs.push(tab)
        }
        return tab
    }
    let tabTop = 0
    for (const panel of panels) {
        if (!panel || typeof panel !== 'object') {
            continue
        }
        if (panel.type === 'row' && panel.__tab) {
            const title = String(panel.title || 'Tab')
            tab = { id: tabId(title), title, tiles: [] }
            tabs.push(tab)
            tabTop = int(panel.gridPos?.y, 0) + 1
            section = undefined
            continue
        }
        if (panel.type === 'row') {
            const rowY = int(panel.gridPos?.y, 0)
            const title = String(panel.title || 'Row')
            const collapsed = !!panel.collapsed
            const tiles: Tile[] = []
            const tile: Tile = {
                id: converter.nextId(title),
                place: { x: 0, y: toRows(Math.max(0, rowY - tabTop)), w: GRID.columns, h: GRID.collapsedSectionRows },
                panel: { type: 'section', title, tiles, ...(collapsed ? { collapsed } : {}) },
            }
            currentTab().tiles.push(tile)
            section = { tile, top: rowY + 1, tiles }
            for (const nested of Array.isArray(panel.panels) ? panel.panels : []) {
                tiles.push(convertPanel(nested, converter, section.top))
            }
            continue
        }
        if (section) {
            section.tiles.push(convertPanel(panel, converter, section.top))
        } else {
            currentTab().tiles.push(convertPanel(panel, converter, tabTop))
        }
    }
    if (tabs.length === 0) {
        currentTab()
    }
    return tabs
}

/** Pre-v5 dashboards: `rows[]` with `span` widths out of 12 instead of grid positions. */
function legacyRows(rows: Json[]): Json[] {
    let y = 0
    return rows.flatMap((row) => {
        const out: Json[] = []
        if (row?.title && row.showTitle) {
            out.push({ type: 'row', title: row.title, collapsed: row.collapse, gridPos: { x: 0, y: y++, w: 24, h: 1 } })
        }
        const h = Math.max(4, Math.round((parseInt(String(row?.height ?? 250), 10) || 250) / 30))
        let x = 0
        for (const panel of row?.panels ?? []) {
            const w = Math.max(1, Math.min(24, Math.round((Number(panel.span) || 12) * 2)))
            if (x + w > 24) {
                x = 0
                y += h
            }
            out.push({ ...panel, gridPos: { x, y, w, h } })
            x += w
        }
        y += h
        return out
    })
}

export function grafanaRoot(input: Json): Json {
    const root = input?.dashboard ?? input
    if (root?.kind === 'Dashboard' && root.spec && typeof root.spec === 'object') {
        return root.spec
    }
    return root
}

export function isGrafanaV2(root: Json): boolean {
    return !!root?.elements && !!root?.layout && !root?.panels
}

export function importGrafana(input: unknown): ImportResult {
    let root = grafanaRoot(input)
    if (!root || typeof root !== 'object' || Array.isArray(root)) {
        throw new Error("This isn't a Grafana dashboard.")
    }
    const v2 = isGrafanaV2(root)
    const report = reportBuilder(v2 ? 'grafana-v2' : 'grafana')
    const warnings: string[] = []
    if (v2) {
        root = fromV2(root, warnings)
    }

    const datasourceVariables = new Map<string, string>()
    const values = new Map<string, string>()
    const variables: ImportedVariable[] = []
    for (const variable of root.templating?.list ?? []) {
        if (!variable?.name) {
            continue
        }
        const name = String(variable.name)
        if (variable.type === 'datasource') {
            datasourceVariables.set(name, String(variable.query ?? ''))
            continue
        }
        const value = variableValue(variable)
        if (value !== undefined) {
            values.set(name, value)
        }
        variables.push({ name, kind: String(variable.type ?? 'unknown'), ...(value !== undefined ? { value } : {}) })
    }
    for (const input of root.__inputs ?? []) {
        if (input?.type === 'datasource' && input.name) {
            datasourceVariables.set(String(input.name), String(input.pluginId ?? ''))
        }
    }
    const fromReference = (text: string): string | undefined => {
        const variable = /^\$\{?(\w+)(?::\w+)?\}?$/.exec(text.trim())
        if (variable) {
            return datasourceVariables.get(variable[1]) ?? 'unknown'
        }
        const lowered = text.toLowerCase()
        if (lowered.startsWith('-- ')) {
            return undefined
        }
        return lowered.includes('loki')
            ? 'loki'
            : lowered.includes('clickhouse')
              ? 'grafana-clickhouse-datasource'
              : lowered.includes('cloudwatch')
                ? 'cloudwatch'
                : /prom|victoria|vm|mimir|thanos|cortex/.test(lowered)
                  ? 'prometheus'
                  : undefined
    }
    const datasourceType = (datasource: Json): string | undefined => {
        if (datasource === null || datasource === undefined) {
            return undefined
        }
        if (typeof datasource === 'string') {
            return fromReference(datasource)
        }
        if (datasource.type && datasource.type !== 'datasource') {
            return String(datasource.type)
        }
        return typeof datasource.uid === 'string' ? fromReference(datasource.uid) : undefined
    }

    const title = String(root.title || 'Imported dashboard')
    const panels: Json[] = Array.isArray(root.panels) ? root.panels : legacyRows(root.rows ?? [])
    const tabs = layoutPanels(panels, { report, variables: values, nextId: idMaker('g'), datasourceType }, title)

    report.report.variables = variables
    if (variables.length > 0) {
        report.note("Boards don't have variables yet, so each query uses the value its variable was saved with.")
    }
    const from = String(root.time?.from ?? 'now-6h')
    const to = String(root.time?.to ?? 'now')
    const time = isBoardTime(from) && isBoardTime(to) ? { from, to } : undefined
    if (!time) {
        report.note(`The time range ${from} to ${to} can't be used here, so the board uses its default.`)
    }
    if (typeof root.refresh === 'string' && root.refresh) {
        report.note(`It refreshed every ${root.refresh} in Grafana. Set auto refresh on the board to match.`)
    }
    if (typeof root.timezone === 'string' && root.timezone && root.timezone !== 'browser') {
        report.note(`It showed times in ${root.timezone}. Boards show times in the project's timezone.`)
    }
    if (root.annotations?.list?.some((annotation: Json) => !annotation.builtIn)) {
        report.note("Annotations aren't imported.")
    }
    warnings.forEach(report.note)

    const dashboard: Dashboard = {
        version: 2,
        title,
        ...(root.description ? { description: String(root.description) } : {}),
        ...(time ? { time } : {}),
        tabs,
    }
    return { dashboard, report: report.finish() }
}
