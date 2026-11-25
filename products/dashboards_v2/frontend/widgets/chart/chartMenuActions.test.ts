import type { ContentWidget } from '../../dashboard/dashboardTypes'
import type { TileAction } from '../../tiles/tileAction'
import { chartMenuActions } from './chartMenuActions'
import type { ChartConfig } from './chartSpec'
import { barSpec } from './viz/bar/barSpec'
import { lineSpec } from './viz/line/lineSpec'
import { statSpec } from './viz/stat/statSpec'

const query = { language: 'hogql', query: 'select 1' } as const

function select(widget: ContentWidget<ChartConfig>, path: string[]): ChartConfig | undefined {
    let saved: ChartConfig | undefined
    let entries: TileAction[] = chartMenuActions([statSpec, lineSpec, barSpec], {
        widget,
        setConfig: (config) => (saved = config),
        disabledReason: null,
    })
    for (const key of path) {
        const entry = entries.find((candidate) => candidate.key === key)!
        if (entry.submenu) {
            entries = entry.submenu
        } else {
            entry.onSelect?.()
        }
    }
    return saved
}

describe('chartMenuActions', () => {
    test.each<{ name: string; viz: ChartConfig['viz']; path: string[]; expected: ChartConfig['viz'] }>([
        {
            name: 'switches the kind of chart and drops options the new kind does not have',
            viz: { type: 'bar', options: { stack: true } },
            path: ['chart-type', 'line'],
            expected: { type: 'line' },
        },
        {
            name: 'turns on a boolean option',
            viz: { type: 'bar' },
            path: ['chart-options', 'stack'],
            expected: { type: 'bar', options: { stack: true } },
        },
        {
            name: 'picks a value for an enum option',
            viz: { type: 'stat' },
            path: ['chart-options', 'format', 'currency'],
            expected: { type: 'stat', options: { format: 'currency' } },
        },
    ])('$name', ({ viz, path, expected }) => {
        expect(select({ type: 'chart', config: { query, viz } }, path)).toEqual({ query, viz: expected })
    })
})
