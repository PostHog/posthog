import { validateDashboard } from '../dashboard/validateDashboard'
import { DEFAULT_PANELS } from '../panels/defaultPanels'
import { grafanaRoot, importGrafana } from './grafanaImport'
import type { ImportResult } from './importReport'
import { importNewRelic, isNewRelic } from './newRelicImport'

export type { ImportResult } from './importReport'

/**
 * Reads a pasted or uploaded export and converts it with the importer for its source. Text before the JSON, such as
 * a line copied along with it, is skipped.
 */
export function importDashboard(text: string): ImportResult | { error: string } {
    const result = convert(text)
    if ('error' in result) {
        return result
    }
    // A tile the query batch endpoint rejects fails every other tile's query in the same batch, so it can't open.
    const [problem] = validateDashboard(result.dashboard, DEFAULT_PANELS)
    return problem ? { error: `This board can't be opened: ${problem.path}: ${problem.message}` } : result
}

function convert(text: string): ImportResult | { error: string } {
    const parsed = parseJson(text)
    if (parsed === undefined) {
        return { error: "This isn't JSON. Paste a Grafana or New Relic dashboard export." }
    }
    try {
        if (isNewRelic(parsed)) {
            return importNewRelic(parsed)
        }
        const root = grafanaRoot(parsed)
        if (root && (Array.isArray(root.panels) || Array.isArray(root.rows) || (root.elements && root.layout))) {
            return importGrafana(parsed)
        }
    } catch (error) {
        return { error: error instanceof Error ? error.message : String(error) }
    }
    return { error: "This doesn't look like a Grafana or New Relic dashboard export." }
}

function parseJson(text: string): any | undefined {
    for (const start of [0, text.indexOf('{')]) {
        if (start < 0) {
            continue
        }
        try {
            return JSON.parse(text.slice(start))
        } catch {
            continue
        }
    }
    return undefined
}
