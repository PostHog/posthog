import type { ContentWidget, Dashboard, Tile } from '../layout/dashboardTypes'

const sql = (expr: string): { kind: 'hogql'; sql: string } => ({ kind: 'hogql', sql: expr })

const stat = (title: string, format?: ContentWidget['format']): ContentWidget => ({
    type: 'stat',
    title,
    format,
    query: sql(`select count() as ${title}`),
})
const line = (title: string): ContentWidget => ({
    type: 'line',
    title,
    query: sql(`select count() from events where chart = '${title}' by day`),
})
const bar = (title: string): ContentWidget => ({
    type: 'bar',
    title,
    query: sql(`select count() from events where chart = '${title}' by country`),
})
const text = (markdown: string): ContentWidget => ({ type: 'markdown', text: markdown })

const tile = (id: string, x: number, y: number, w: number, h: number, widget: Tile['widget']): Tile => ({
    id,
    place: { x, y, w, h },
    widget,
})
const section = (id: string, x: number, y: number, w: number, title: string, tiles: Tile[], collapsed = false): Tile =>
    tile(id, x, y, w, 1, { type: 'section', title, tiles, collapsed })

const statRow = (prefix: string, y: number, cols: number, titles: string[]): Tile[] => {
    const w = Math.floor(cols / titles.length)
    return titles.map((title, index) => tile(`${prefix}-${index}`, index * w, y, w, 3, stat(title)))
}

const BIG_TILE_COUNT = 120

export const kitchenSinkDashboard: Dashboard = {
    version: 2,
    title: 'Dashboards v2',
    tabs: [
        {
            id: 'kitchen-sink',
            title: 'Kitchen sink',
            tiles: [
                ...statRow('ks-stat', 0, 24, ['Visitors', 'Sessions', 'Signups', 'Revenue']),
                tile('ks-trend', 0, 3, 16, 8, line('Signups over time')),
                tile('ks-notes', 16, 3, 8, 8, text('## Notes\n\nDrag a tile by its title. Resize it from its left, right or bottom edge.')),
                section('ks-section', 0, 11, 24, 'Section with tiles', [
                    tile('ks-s-bar', 0, 0, 12, 7, bar('Signups by country')),
                    tile('ks-s-line', 12, 0, 12, 7, line('Activation')),
                ]),
                section('ks-nested', 0, 20, 24, 'Section with a section inside', [
                    tile('ks-n-stat', 0, 0, 6, 3, stat('Errors')),
                    tile('ks-n-stat2', 6, 0, 6, 3, stat('Error rate', 'percentage')),
                    section('ks-inner', 12, 0, 12, 'Inner section', [
                        tile('ks-i-line', 0, 0, 12, 6, line('Errors over time')),
                    ]),
                ]),
                section('ks-left', 0, 32, 12, 'Half width', [tile('ks-l-bar', 0, 0, 12, 6, bar('Plans'))]),
                section('ks-right', 12, 32, 12, 'Half width, empty', []),
                section('ks-closed', 0, 42, 24, 'Closed section', [tile('ks-c-line', 0, 0, 24, 6, line('Hidden'))], true),
                tile('ks-headless', 0, 44, 8, 4, text('A tile without a title is dragged by its body.')),
            ],
        },
        {
            id: 'web-analytics',
            title: 'Web analytics',
            tiles: [
                ...statRow('wa-stat', 0, 24, ['Visitors', 'Page views', 'Sessions', 'Session duration', 'Bounce rate']),
                tile('wa-trend', 0, 3, 24, 9, line('Unique visitors')),
                tile('wa-paths', 0, 12, 12, 9, bar('Paths')),
                tile('wa-sources', 12, 12, 12, 9, bar('Sources')),
                tile('wa-devices', 0, 21, 12, 8, bar('Device types')),
                tile('wa-geo', 12, 21, 12, 8, bar('Countries')),
                section('wa-goals', 0, 29, 24, 'Goals', [
                    tile('wa-goal-trend', 0, 0, 16, 7, line('Goal conversions')),
                    tile('wa-goal-rate', 16, 0, 8, 3, stat('Conversion rate', 'percentage')),
                    tile('wa-goal-total', 16, 3, 8, 4, stat('Conversions')),
                ]),
            ],
        },
        {
            id: 'ai-observability',
            title: 'AI observability',
            tiles: [
                ...statRow('aio-stat', 0, 24, ['Traces', 'Generations', 'Users', 'Total cost']),
                tile('aio-cost', 0, 3, 12, 8, line('Cost by model')),
                tile('aio-latency', 12, 3, 12, 8, line('Generation latency')),
                section('aio-usage', 0, 11, 24, 'Usage', [
                    tile('aio-tokens', 0, 0, 8, 7, bar('Tokens by model')),
                    tile('aio-calls', 8, 0, 8, 7, line('Generations over time')),
                    tile('aio-users', 16, 0, 8, 7, bar('Cost per user')),
                ]),
                section('aio-errors', 0, 20, 24, 'Errors', [
                    tile('aio-error-rate', 0, 0, 6, 3, stat('Error rate', 'percentage')),
                    tile('aio-error-trend', 6, 0, 18, 6, line('Errors over time')),
                ]),
            ],
        },
        {
            id: 'marketing',
            title: 'Marketing analytics',
            tiles: [
                ...statRow('mk-stat', 0, 24, ['Spend', 'Clicks', 'Impressions', 'Conversions', 'CPC', 'ROAS']),
                tile('mk-trend', 0, 3, 24, 8, line('Spend and conversions')),
                section('mk-google', 0, 11, 12, 'Google Ads', [
                    ...statRow('mk-g', 0, 12, ['Spend', 'ROAS']),
                    tile('mk-g-bar', 0, 3, 12, 6, bar('Campaigns')),
                ]),
                section('mk-meta', 12, 11, 12, 'Meta Ads', [
                    ...statRow('mk-m', 0, 12, ['Spend', 'ROAS']),
                    tile('mk-m-bar', 0, 3, 12, 6, bar('Campaigns')),
                ]),
            ],
        },
        {
            id: 'big',
            title: `${BIG_TILE_COUNT} tiles`,
            tiles: Array.from({ length: BIG_TILE_COUNT }, (_, index) =>
                tile(
                    `big-${index}`,
                    (index % 4) * 6,
                    Math.floor(index / 4) * 6,
                    6,
                    6,
                    index % 3 === 0 ? bar(`Bar ${index}`) : line(`Line ${index}`)
                )
            ),
        },
    ],
}
