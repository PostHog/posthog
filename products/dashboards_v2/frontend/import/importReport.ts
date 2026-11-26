import type { PanelQuery } from '../dashboard/dashboardSchema'
import type { ContentPanel, Dashboard, TilePlace, TimeRange, Tile } from '../dashboard/dashboardTypes'
import type { ChartConfig, ChartTarget } from '../panels/chart/chartSpec'
import { barSpec } from '../panels/chart/viz/bar/barSpec'
import { lineSpec } from '../panels/chart/viz/line/lineSpec'
import { statSpec } from '../panels/chart/viz/stat/statSpec'
import { markdownSpec } from '../panels/markdown/markdownSpec'

export type ImportSource = 'grafana' | 'grafana-v2'

/**
 * - `mapped`: the tile shows what it showed before.
 * - `partial`: the tile runs, but something about it differs, such as a chart type we don't have.
 * - `unsupported`: the tile is a note that says why, with the original queries, so nothing is dropped silently.
 */
export type TileStatus = 'mapped' | 'partial' | 'unsupported'

export interface TileReport {
    tileId: string
    title: string
    from: string
    status: TileStatus
    reasons: string[]
}

/** The data the board reads. Whether this project has it is checked later, against the project. */
export interface ImportRequirements {
    events: string[]
    properties: string[]
    metrics: string[]
    logStreams: string[]
}

/** A dashboard variable. Boards have no variables yet, so each query uses the value it was saved with. */
export interface ImportedVariable {
    name: string
    kind: string
    value?: string
}

export interface ImportReport {
    source: ImportSource
    tiles: TileReport[]
    queries: { total: number; translated: number }
    requires: ImportRequirements
    variables: ImportedVariable[]
    notes: string[]
}

export interface ImportResult {
    dashboard: Dashboard
    report: ImportReport
}

export interface ReportBuilder {
    report: ImportReport
    tile: (tile: TileReport) => void
    require: (kind: keyof ImportRequirements, name: string) => void
    query: (translated: boolean) => void
    note: (note: string) => void
    finish: () => ImportReport
}

export function reportBuilder(source: ImportSource): ReportBuilder {
    const requires = {
        events: new Set<string>(),
        properties: new Set<string>(),
        metrics: new Set<string>(),
        logStreams: new Set<string>(),
    }
    const report: ImportReport = {
        source,
        tiles: [],
        queries: { total: 0, translated: 0 },
        requires: { events: [], properties: [], metrics: [], logStreams: [] },
        variables: [],
        notes: [],
    }
    return {
        report,
        tile: (tile) => report.tiles.push(tile),
        require: (kind, name) => requires[kind].add(name),
        query: (translated) => {
            report.queries.total++
            report.queries.translated += translated ? 1 : 0
        },
        note: (note) => {
            if (!report.notes.includes(note)) {
                report.notes.push(note)
            }
        },
        finish: () => {
            report.requires = {
                events: [...requires.events].sort(),
                properties: [...requires.properties].sort(),
                metrics: [...requires.metrics].sort(),
                logStreams: [...requires.logStreams].sort(),
            }
            return report
        },
    }
}

export function tileCounts(report: ImportReport): Record<TileStatus, number> {
    const counts: Record<TileStatus, number> = { mapped: 0, partial: 0, unsupported: 0 }
    for (const tile of report.tiles) {
        counts[tile.status]++
    }
    return counts
}

export function idMaker(prefix: string): (title: string) => string {
    const used = new Set<string>()
    return (title) => {
        const base = `${prefix}-${title
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '')
            .slice(0, 40)}`.replace(/-$/, '')
        let id = base
        for (let n = 2; used.has(id); n++) {
            id = `${base}-${n}`
        }
        used.add(id)
        return id
    }
}

// Long queries would make a note taller than any tile it replaces.
const MAX_NOTE_QUERY = 1500

function fence(language: string, text: string): string {
    const body = text.length > MAX_NOTE_QUERY ? `${text.slice(0, MAX_NOTE_QUERY)}\n…` : text
    return `\`\`\`${language}\n${body}\n\`\`\``
}

export function notePanel(
    title: string | undefined,
    heading: string,
    queries: { language: string; text: string }[]
): ContentPanel {
    const original = queries.map((query) => fence(query.language, query.text)).join('\n\n')
    return {
        type: 'markdown',
        ...(title ? { title } : {}),
        config: { text: original ? `${heading}\n\n${original}` : heading },
    }
}

// The query batch endpoint rejects a chart with more targets, and with it every other tile in the batch.
export const MAX_TARGETS = 26

export function chartPanel(
    title: string | undefined,
    description: string | undefined,
    targets: { query: PanelQuery; legend?: string; refId: string }[],
    viz: ChartConfig['viz'],
    time?: TimeRange
): ContentPanel<ChartConfig> {
    const config: ChartConfig =
        targets.length === 1 && !targets[0].legend
            ? { query: targets[0].query, viz }
            : {
                  targets: targets.map(
                      (target): ChartTarget => ({
                          refId: target.refId,
                          query: target.query,
                          ...(target.legend ? { legend: target.legend } : {}),
                      })
                  ),
                  viz,
              }
    return {
        type: 'chart',
        ...(title ? { title } : {}),
        ...(description ? { description } : {}),
        config: time ? { ...config, time } : config,
    }
}

export function isBoardTime(end: string): boolean {
    return end === 'now' || /^now-\d+[smhdwMy]$/.test(end) || !Number.isNaN(Date.parse(end))
}

const MIN_SIZES: Record<string, { minW: number; minH: number }> = {
    markdown: markdownSpec.size,
    line: lineSpec.size,
    bar: barSpec.size,
    stat: statSpec.size,
}

/**
 * A tile at least as big as its panel allows. Growing a tile can make it overlap the next one, which loading the
 * board settles by moving tiles down.
 */
export function importedTile(id: string, place: TilePlace, panel: Tile['panel']): Tile {
    const kind = panel.type === 'chart' ? (panel as ContentPanel<ChartConfig>).config.viz.type : panel.type
    const min = MIN_SIZES[kind]
    if (!min) {
        return { id, place, panel }
    }
    const w = Math.max(place.w, min.minW)
    const x = Math.min(place.x, 24 - w)
    return { id, place: { x, y: place.y, w, h: Math.max(place.h, min.minH) }, panel }
}
