import { chartSpec } from '../widgets/chart/chartSpec'
import { barSpec } from '../widgets/chart/viz/bar/barSpec'
import { lineSpec } from '../widgets/chart/viz/line/lineSpec'
import { statSpec } from '../widgets/chart/viz/stat/statSpec'
import { markdownSpec } from '../widgets/markdown/markdownSpec'
import type { DashboardProblem } from './validateDashboard'
import { validateDashboard } from './validateDashboard'

// Specs only, with no components, as a CI check or an MCP tool would load them.
const SPECS = [chartSpec([statSpec, lineSpec, barSpec]), markdownSpec]
const withTiles = (tiles: unknown[]): unknown => ({
    version: 2,
    title: 'Test',
    tabs: [{ id: 'tab', title: 'Tab', tiles }],
})
const note = { type: 'markdown', config: { text: 'hi' } }

describe('validateDashboard', () => {
    test.each<{ name: string; document: unknown; expected: DashboardProblem[] }>([
        ...['javascript:alert(1)', '//example.com/phish'].map((href) => ({
            name: `a link tab to ${href}`,
            document: {
                version: 2,
                title: 'Test',
                tabs: [
                    { id: 'tab', title: 'Tab', tiles: [] },
                    { id: 'link', title: 'Link', href },
                ],
            },
            expected: [{ path: expect.stringMatching(/^tabs\[1\]/), message: expect.any(String) }],
        })),
        {
            name: 'an unknown widget type',
            document: withTiles([{ id: 'a', place: { x: 0, y: 0, w: 6, h: 4 }, widget: { type: 'lnie' } }]),
            expected: [
                {
                    path: 'tabs[0].tiles[0].widget.type',
                    message: 'Unknown widget type "lnie". Known types: chart, markdown',
                },
            ],
        },
        {
            name: 'a chart without its query',
            document: withTiles([
                {
                    id: 'a',
                    place: { x: 0, y: 0, w: 12, h: 8 },
                    widget: { type: 'chart', config: { viz: { type: 'line' } } },
                },
            ]),
            expected: [{ path: 'tabs[0].tiles[0].widget.config.query', message: expect.any(String) }],
        },
        {
            name: 'a metrics query that is not a MetricsQuery node',
            document: withTiles([
                {
                    id: 'a',
                    place: { x: 0, y: 0, w: 12, h: 8 },
                    widget: {
                        type: 'chart',
                        config: {
                            query: { language: 'metrics', query: { kind: 'TrendsQuery' } },
                            viz: { type: 'line' },
                        },
                    },
                },
            ]),
            expected: [{ path: 'tabs[0].tiles[0].widget.config.query', message: expect.any(String) }],
        },
        {
            name: 'a chart type the host does not offer',
            document: withTiles([
                {
                    id: 'a',
                    place: { x: 0, y: 0, w: 12, h: 8 },
                    widget: {
                        type: 'chart',
                        config: { query: { language: 'hogql', query: 'select 1' }, viz: { type: 'pie' } },
                    },
                },
            ]),
            expected: [{ path: 'tabs[0].tiles[0].widget.config.viz', message: expect.any(String) }],
        },
        {
            name: 'a misspelled config field',
            document: withTiles([
                { id: 'a', place: { x: 0, y: 0, w: 8, h: 4 }, widget: { type: 'markdown', config: { txt: 'hi' } } },
            ]),
            expected: [
                { path: 'tabs[0].tiles[0].widget.config.text', message: expect.any(String) },
                { path: 'tabs[0].tiles[0].widget.config', message: expect.stringContaining('txt') },
            ],
        },
        {
            name: 'a misspelled widget field',
            document: withTiles([{ id: 'a', place: { x: 0, y: 0, w: 8, h: 4 }, widget: { ...note, titel: 'x' } }]),
            expected: [{ path: 'tabs[0].tiles[0].widget', message: expect.stringContaining('titel') }],
        },
        {
            name: 'a tile smaller than its widget allows',
            document: withTiles([{ id: 'a', place: { x: 0, y: 0, w: 1, h: 4 }, widget: note }]),
            expected: [
                {
                    path: 'tabs[0].tiles[0].place',
                    message: 'This markdown tile is at least 3 columns wide and 4 rows tall',
                },
            ],
        },
        {
            name: 'a tile past the edge of the section it sits in',
            document: withTiles([
                {
                    id: 's',
                    place: { x: 0, y: 0, w: 6, h: 3 },
                    widget: {
                        type: 'section',
                        title: 'S',
                        tiles: [{ id: 'a', place: { x: 2, y: 0, w: 6, h: 4 }, widget: note }],
                    },
                },
            ]),
            expected: [
                { path: 'tabs[0].tiles[0].widget.tiles[0].place', message: "The tile goes past the grid's 6 columns" },
            ],
        },
        {
            name: 'two tiles with one id',
            document: withTiles([
                { id: 'a', place: { x: 0, y: 0, w: 8, h: 4 }, widget: note },
                { id: 'a', place: { x: 8, y: 0, w: 8, h: 4 }, widget: note },
            ]),
            expected: [{ path: 'tabs[0].tiles[1].id', message: 'The id "a" is used by another tile or tab' }],
        },
        {
            name: 'a document that is not a v2 dashboard',
            document: { version: 1, title: 'Old', tabs: [] },
            expected: [
                { path: 'version', message: expect.any(String) },
                { path: 'tabs', message: expect.any(String) },
            ],
        },
    ])('reports $name', ({ document, expected }) => {
        expect(validateDashboard(document, SPECS)).toEqual(expected)
    })
})
