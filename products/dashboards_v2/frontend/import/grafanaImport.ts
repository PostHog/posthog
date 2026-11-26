import type { PanelQuery } from '../dashboard/dashboardSchema'
import { type Dashboard, GRID, type GridTab, type Tile } from '../dashboard/dashboardTypes'
import type { ChartConfig } from '../panels/chart/chartSpec'
import type { StatOptions } from '../panels/chart/viz/stat/statSpec'
import { fromV2 } from './grafanaV2'
import {
    type ImportResult,
    type ImportedVariable,
    type ReportBuilder,
    type TileStatus,
    MAX_TARGETS,
    chartPanel,
    idMaker,
    importedTile,
    isBoardTime,
    notePanel,
    reportBuilder,
} from './importReport'
import { own } from './nrql'
import {
    fillVariables,
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
    return values.length === 1 ? values[0] : values.join('|')
}

interface Converter {
    report: ReportBuilder
    variables: Map<string, string>
    nextId: (title: string) => string
    datasourceType: (datasource: unknown) => string | undefined
}

function convertPanel(panel: Json, converter: Converter, top: number): Tile {
    const { report } = converter
    const title = panel.title ? String(panel.title) : undefined
    const description = panel.description ? String(panel.description) : undefined
    const id = converter.nextId(title || panel.type || 'panel')
    const gridPos = panel.gridPos ?? {}
    const x = Math.min(23, Math.max(0, int(gridPos.x, 0)))
    const y = Math.max(0, int(gridPos.y, 0) - top)
    const place = {
        x,
        y: toRows(y),
        w: Math.min(24 - x, Math.max(1, int(gridPos.w, 12))),
        h: Math.max(1, toRows(y + Math.max(1, int(gridPos.h, 8))) - toRows(y)),
    }
    const reasons: string[] = []
    const done = (content: Tile['panel'], status: TileStatus): Tile => {
        report.tile({ tileId: id, title: title ?? '', from: String(panel.type ?? 'panel'), status, reasons })
        return importedTile(id, place, content)
    }

    if (panel.libraryPanel && !panel.type) {
        const name = panel.libraryPanel.name ?? panel.libraryPanel.uid
        reasons.push(`Library panel "${name}" isn't part of the export.`)
        return done(notePanel(title, `**Not supported yet:** library panel \`${name}\`.`, []), 'unsupported')
    }
    if (panel.type === 'text') {
        return done(
            {
                type: 'markdown',
                ...(title ? { title } : {}),
                config: { text: String(panel.options?.content ?? panel.content ?? '') },
            },
            'mapped'
        )
    }

    const targets: { refId: string; query: PanelQuery; legend?: string }[] = []
    const skipped: { language: string; text: string }[] = []
    const panelType = converter.datasourceType(panel.datasource)
    for (const [index, target] of (Array.isArray(panel.targets) ? panel.targets : []).entries()) {
        if (!target || typeof target !== 'object' || target.hide) {
            continue
        }
        const refId = String(target.refId ?? String.fromCharCode(65 + index))
        const expr = typeof target.expr === 'string' ? target.expr : undefined
        let type = converter.datasourceType(target.datasource) ?? (panelType === 'unknown' ? undefined : panelType)
        if (expr !== undefined && (type === undefined || type === 'unknown')) {
            type = looksLikeLogql(expr) ? 'loki' : 'prometheus'
        }
        if (expr !== undefined && !expr.trim()) {
            continue
        }
        const legend = target.legendFormat && target.legendFormat !== '__auto' ? String(target.legendFormat) : undefined
        if (expr !== undefined && (PROMETHEUS.has(type ?? '') || type === 'loki')) {
            const loki = type === 'loki'
            const cleaned = expr.replace(/\$\{DS_[A-Z0-9_]+\}/g, '')
            const filled = fillVariables(loki ? cleaned : stripStepWindows(cleaned), converter.variables)
            for (const name of filled.unfilled) {
                reasons.push(`$${name} has no saved value, so ${refId} keeps it as written and may not run.`)
            }
            if (!loki) {
                for (const name of metricsqlFunctions(filled.text)) {
                    reasons.push(`${refId} uses the MetricsQL function ${name}(), which PostHog may not run.`)
                }
                promqlMetrics(filled.text)
                    .filter((name) => !name.startsWith('$'))
                    .forEach((name) => report.require('metrics', name))
            } else {
                logqlStreams(filled.text).forEach((stream) => report.require('logStreams', rewriteLogql(stream)))
            }
            const query: PanelQuery = loki
                ? { language: 'logql', query: rewriteLogql(filled.text) }
                : { language: 'promql', query: filled.text }
            report.query(filled.unfilled.length === 0)
            targets.push({ refId, query, legend: legend && loki ? logqlLegend(legend) : legend })
            continue
        }
        const text =
            [target.rawSql, target.expr, target.expression, target.query, target.sqlExpression].find(
                (candidate) => typeof candidate === 'string' && candidate.trim()
            ) ?? ''
        const language = own(DATASOURCE_NAMES, type ?? '') ?? type ?? 'an unknown datasource'
        report.query(false)
        skipped.push({ language: /sql/i.test(language) ? 'sql' : '', text: `-- ${refId} · ${language}\n${text}` })
        reasons.push(`${refId} queries ${language}, which PostHog can't run.`)
    }

    const viz = own(VIZ, String(panel.type))
    if (!viz) {
        reasons.unshift(`Grafana panel type "${panel.type}" has no equivalent yet.`)
        const original = [
            ...targets.map((t) => ({ language: t.query.language, text: String(t.query.query) })),
            ...skipped,
        ]
        return done(notePanel(title, `**Not supported yet:** ${panel.type}`, original), 'unsupported')
    }
    if (targets.length === 0) {
        return done(
            notePanel(title, `**Not supported yet:** this ${panel.type} panel has no query PostHog can run.`, skipped),
            'unsupported'
        )
    }
    if (viz.lossy) {
        reasons.unshift(viz.lossy)
    }
    if (targets.length > MAX_TARGETS) {
        reasons.push(`Only the first ${MAX_TARGETS} of its ${targets.length} queries are kept.`)
        targets.length = MAX_TARGETS
    }
    const format = viz.type === 'stat' ? statFormat(panel.fieldConfig?.defaults?.unit ?? panel.format) : undefined
    const vizConfig: ChartConfig['viz'] = format
        ? { type: 'stat', options: { format } }
        : panel.fieldConfig?.defaults?.custom?.stacking?.mode === 'normal' && viz.type === 'bar'
          ? { type: 'bar', options: { stack: true } }
          : { type: viz.type }
    return done(chartPanel(title, description, targets, vizConfig), reasons.length ? 'partial' : 'mapped')
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
