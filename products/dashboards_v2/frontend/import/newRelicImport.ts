import type { Dashboard, GridTab, Tile } from '../dashboard/document/dashboardTypes'
import type { TimeRange } from '../filters/time/timeRangeSchema'
import type { ChartConfig } from '../panels/chart/chartSpec'
import type { PanelQuery } from '../query/querySchema'
import {
    type ImportResult,
    type TileStatus,
    MAX_TARGETS,
    chartPanel,
    idMaker,
    importedTile,
    inline,
    notePanel,
    reportBuilder,
} from './importReport'
import { type NrqlTranslation, own, translateNrql } from './nrql'

/**
 * A New Relic dashboard export as a board: each page is a tab, each widget a tile, and each NRQL query HogQL through
 * `translateNrql`. A widget whose queries don't translate becomes a note with the original NRQL. Account ids are
 * dropped, so nothing in the board points at the New Relic account.
 */

type Json = any // eslint-disable-line @typescript-eslint/no-explicit-any

const VIZ: Record<string, { viz: ChartConfig['viz']; lossy?: string }> = {
    'viz.billboard': { viz: { type: 'metric' } },
    'viz.line': { viz: { type: 'line' } },
    'viz.area': { viz: { type: 'line' }, lossy: 'There is no area chart yet, so it shows as lines.' },
    'viz.bar': { viz: { type: 'bar' } },
    'viz.stacked-bar': { viz: { type: 'bar', options: { stack: true } } },
    'viz.table': { viz: { type: 'bar' }, lossy: 'There is no table chart yet, so it shows as bars.' },
    'viz.pie': { viz: { type: 'bar' }, lossy: 'There is no pie chart yet, so it shows as bars.' },
    'viz.histogram': { viz: { type: 'bar' }, lossy: 'There is no histogram yet, so it shows as bars.' },
}

// New Relic lays widgets on a 12 column grid of rows about 100px tall. Ours has 24 columns of 22px steps.
const COLUMN_SCALE = 2
const ROW_SCALE = 5
// A query without SINCE covers the last hour in New Relic.
const NEW_RELIC_DEFAULT_TIME: TimeRange = { from: 'now-1h', to: 'now' }

const sameTime = (a: TimeRange, b: TimeRange): boolean => a.from === b.from && a.to === b.to
const int = (value: unknown, fallback: number): number =>
    Number.isFinite(Number(value)) && Number(value) > 0 ? Math.round(Number(value)) : fallback

export function isNewRelic(input: Json): boolean {
    return Array.isArray(input?.pages)
}

export function importNewRelic(input: unknown): ImportResult {
    const root = input as Json
    if (!isNewRelic(root)) {
        throw new Error("This isn't a New Relic dashboard.")
    }
    const report = reportBuilder('newrelic')
    const nextId = idMaker('nr')
    const tabId = idMaker('tab')

    interface Pending {
        tile: Tile
        time: TimeRange | undefined
        ignoreTimeRange: boolean
    }
    const pending: Pending[] = []
    const votes = new Map<string, { time: TimeRange; count: number }>()

    const tabs: GridTab[] = (root.pages as Json[]).map((page, pageIndex) => {
        const title = String(page?.name || `Page ${pageIndex + 1}`)
        const tiles = (Array.isArray(page?.widgets) ? page.widgets : []).map((widget: Json) => {
            const config = widget?.rawConfiguration ?? {}
            const vizId = String(widget?.visualization?.id ?? 'unknown')
            const widgetTitle = widget?.title ? String(widget.title) : undefined
            const id = nextId(widgetTitle || vizId.replace('viz.', ''))
            const layout = widget?.layout ?? {}
            const x = Math.min(11, Math.max(0, int(layout.column, 1) - 1)) * COLUMN_SCALE
            const place = {
                x,
                y: Math.max(0, int(layout.row, 1) - 1) * ROW_SCALE,
                w: Math.min(24 - x, int(layout.width, 4) * COLUMN_SCALE),
                h: int(layout.height, 3) * ROW_SCALE,
            }
            const reasons: string[] = []
            const finish = (content: Tile['panel'], status: TileStatus, time?: TimeRange): Tile => {
                report.tile({ tileId: id, title: widgetTitle ?? '', from: vizId, status, reasons })
                const tile = importedTile(id, place, content)
                const ignoreTimeRange = !!config.platformOptions?.ignoreTimeRange
                pending.push({ tile, time, ignoreTimeRange })
                if (time && !ignoreTimeRange) {
                    const key = `${time.from}|${time.to}`
                    votes.set(key, { time, count: (votes.get(key)?.count ?? 0) + 1 })
                }
                return tile
            }

            if (vizId === 'viz.markdown') {
                return finish(
                    {
                        type: 'markdown',
                        ...(widgetTitle ? { title: widgetTitle } : {}),
                        config: { text: String(config.text ?? '') },
                    },
                    'mapped'
                )
            }
            const queries: string[] = (Array.isArray(config.nrqlQueries) ? config.nrqlQueries : [])
                .map((query: Json) => String(query?.query ?? '').trim())
                .filter(Boolean)
            const translations = queries.map((nrql) => ({ nrql, result: translateNrql(nrql) }))
            const viz = own(VIZ, vizId)
            const overTime = viz !== undefined && viz.viz.type !== 'metric'
            const targets: { refId: string; query: PanelQuery }[] = []
            const failed: string[] = []
            let time: TimeRange | undefined
            for (const [index, { nrql, result }] of translations.entries()) {
                const prefix = queries.length > 1 ? `Query ${index + 1}: ` : ''
                report.query(result.ok)
                result.events.forEach((event) => report.require('events', event))
                if (!result.ok) {
                    failed.push(nrql)
                    reasons.push(`${prefix}${result.reason}`)
                    continue
                }
                const translation: NrqlTranslation = result
                // Line and bar charts only draw values over time so far.
                if (overTime && !translation.timeseries) {
                    failed.push(nrql)
                    reasons.push(`${prefix}It has no TIMESERIES, and this chart only draws values over time so far.`)
                    continue
                }
                // A chart sends one time range to all its queries.
                const queryTime = translation.since ?? NEW_RELIC_DEFAULT_TIME
                if (time && !sameTime(time, queryTime)) {
                    failed.push(nrql)
                    reasons.push(`${prefix}It asks for a different time range than the chart's first query.`)
                    continue
                }
                time = queryTime
                translation.properties.forEach((property) => report.require('properties', property))
                reasons.push(...translation.notes)
                // Line and bar charts draw the first number of each query, so each column gets its own query.
                for (const hogql of (overTime && translation.hogqlPerColumn) || [translation.hogql]) {
                    targets.push({
                        refId: String.fromCharCode(65 + targets.length),
                        query: { language: 'hogql', query: hogql },
                    })
                }
            }

            if (!viz || targets.length === 0) {
                if (!viz) {
                    reasons.unshift(`New Relic's ${vizId} has no equivalent yet.`)
                }
                const heading = viz
                    ? '**Needs translating.** This NRQL has no SQL version yet.'
                    : `**Not supported yet:** \`${inline(vizId)}\``
                return finish(
                    notePanel(
                        widgetTitle,
                        heading,
                        queries.map((text) => ({ language: 'sql', text }))
                    ),
                    'unsupported'
                )
            }
            if (failed.length > 0) {
                reasons.push(
                    `${failed.length} of its ${queries.length} queries need translating, so the chart leaves them out.`
                )
            }
            if (viz.lossy) {
                reasons.unshift(viz.lossy)
            }
            if (targets.length > MAX_TARGETS) {
                targets.length = MAX_TARGETS
                reasons.push(`Only the first ${MAX_TARGETS} queries or columns are kept.`)
            }
            const description = widget?.description ? String(widget.description) : undefined
            return finish(
                chartPanel(widgetTitle, description, targets, viz.viz),
                reasons.length > 0 ? 'partial' : 'mapped',
                time
            )
        })
        return { id: tabId(title), title, tiles }
    })

    // The board's range is the one most widgets ask for. A widget that asks for another keeps its own, so its
    // numbers match New Relic's.
    const boardTime = [...votes.values()].sort((a, b) => b.count - a.count)[0]?.time
    for (const { tile, time, ignoreTimeRange } of pending) {
        if (time && tile.panel.type === 'chart' && (ignoreTimeRange || !boardTime || !sameTime(time, boardTime))) {
            const chart = tile.panel as { config: ChartConfig }
            chart.config = { ...chart.config, time }
        }
    }
    if (Array.isArray(root.variables) && root.variables.length > 0) {
        report.report.variables = root.variables.map((variable: Json) => ({
            name: String(variable?.name ?? ''),
            kind: String(variable?.type ?? 'unknown'),
        }))
        report.note("Boards don't have variables yet, so queries that use them need editing.")
    }

    const dashboard: Dashboard = {
        version: 2,
        title: String(root.name || 'Imported dashboard'),
        ...(root.description ? { description: String(root.description) } : {}),
        ...(boardTime ? { time: boardTime } : {}),
        tabs: tabs.length > 0 ? tabs : [{ id: 'tab-1', title: 'Page 1', tiles: [] }],
    }
    return { dashboard, report: report.finish() }
}
