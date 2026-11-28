import { propertyFilterSpec } from '../../filters/property/propertyFilterSpec'
import { selectFilterSpec } from '../../filters/select/selectFilterSpec'
import { kitchenSinkContents } from '../../fixtures/custom/kitchenSinkContents'
import { kitchenSinkDashboard } from '../../fixtures/kitchenSinkDashboard'
import { BUILT_IN_VIZ_SPECS, chartSpec } from '../../panels/chart/chartSpec'
import { definePanelSpec } from '../../panels/core/panelSpec'
import { customSpec } from '../../panels/custom/customSpec'
import { markdownSpec } from '../../panels/markdown/markdownSpec'
import { dashboardSchema } from './dashboardSchema'
import type { DashboardProblem } from './validateDashboard'
import { MAX_SECTION_DEPTH, validateDashboard } from './validateDashboard'

// Specs only, with no components, as a CI check or an MCP tool would load them.
const SPECS = [
    definePanelSpec(chartSpec(BUILT_IN_VIZ_SPECS)),
    definePanelSpec(markdownSpec),
    definePanelSpec(customSpec([kitchenSinkContents], [])),
]
const FILTER_SPECS = [selectFilterSpec([]), propertyFilterSpec([])]
const withTiles = (tiles: unknown[]): unknown => ({
    version: 2,
    title: 'Test',
    tabs: [{ id: 'tab', title: 'Tab', tiles }],
})
const note = { type: 'markdown', config: { text: 'hi' } }
const nestedSections = (depth: number): unknown =>
    depth === 0
        ? { id: 'leaf', place: { x: 0, y: 0, w: 8, h: 4 }, panel: note }
        : {
              id: `s${depth}`,
              place: { x: 0, y: 0, w: 24, h: 8 },
              panel: { type: 'section', title: 'S', tiles: [nestedSections(depth - 1)] },
          }

describe('validateDashboard', () => {
    it('flags only the kitchen sink tiles that are broken on purpose', () => {
        const broken = 'tabs[2].tiles[4].panel.tiles'
        expect(validateDashboard(kitchenSinkDashboard, SPECS, FILTER_SPECS).map((problem) => problem.path)).toEqual([
            `${broken}[1].panel.type`,
            `${broken}[2].panel.config.viz`,
            `${broken}[3].panel.config.viz`,
            `${broken}[4].panel.config.text`,
            `${broken}[5].panel.config.query`,
            `${broken}[6].panel.config.content`,
        ])
    })

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
            name: 'a tile pointing at a panel the document does not have',
            document: withTiles([{ id: 'a', place: { x: 0, y: 0, w: 8, h: 4 }, panel: { ref: 'gone' } }]),
            expected: [
                {
                    path: 'tabs[0].tiles[0].panel.ref',
                    message: 'There is no panel "gone" in the dashboard\'s panels',
                },
            ],
        },
        {
            name: 'a full panel that also carries a ref, which only a shared panel may have',
            document: withTiles([{ id: 'a', place: { x: 0, y: 0, w: 8, h: 4 }, panel: { ...note, ref: 'note' } }]),
            expected: [{ path: 'tabs[0].tiles[0].panel.ref', message: expect.stringContaining('ref') }],
        },
        {
            name: 'a tile that shows a shared panel and also carries content that would replace it',
            document: {
                ...(withTiles([
                    { id: 'a', place: { x: 0, y: 0, w: 8, h: 4 }, panel: { ref: 'note', config: { text: 123 } } },
                ]) as object),
                panels: { note },
            },
            expected: [{ path: 'tabs[0].tiles[0].panel.config', message: expect.any(String) }],
        },
        {
            name: 'a content panel that carries tiles',
            document: withTiles([{ id: 'a', place: { x: 0, y: 0, w: 8, h: 4 }, panel: { ...note, tiles: null } }]),
            expected: [{ path: 'tabs[0].tiles[0].panel.tiles', message: expect.any(String) }],
        },
        {
            name: 'a tab with both tiles and a link, whose link would skip the scheme check',
            document: {
                version: 2,
                title: 'Test',
                tabs: [{ id: 'tab', title: 'Tab', tiles: [], href: 'javascript:alert(1)' }],
            },
            expected: [{ path: 'tabs[0]', message: expect.any(String) }],
        },
        {
            name: 'a tile smaller than the shared panel it shows',
            document: {
                ...(withTiles([{ id: 'a', place: { x: 0, y: 0, w: 2, h: 4 }, panel: { ref: 'note' } }]) as object),
                panels: { note },
            },
            expected: [
                {
                    path: 'tabs[0].tiles[0].place',
                    message: 'This markdown tile is at least 3 columns wide and 4 rows tall',
                },
            ],
        },
        {
            name: 'an unknown panel type',
            document: withTiles([{ id: 'a', place: { x: 0, y: 0, w: 6, h: 4 }, panel: { type: 'lnie' } }]),
            expected: [
                {
                    path: 'tabs[0].tiles[0].panel.type',
                    message: 'Unknown panel type "lnie". Known types: chart, markdown, custom',
                },
            ],
        },
        {
            name: 'a chart without its query',
            document: withTiles([
                {
                    id: 'a',
                    place: { x: 0, y: 0, w: 12, h: 8 },
                    panel: { type: 'chart', config: { viz: { type: 'line' } } },
                },
            ]),
            expected: [{ path: 'tabs[0].tiles[0].panel.config.query', message: expect.any(String) }],
        },
        {
            name: 'a query node with no kind',
            document: withTiles([
                {
                    id: 'a',
                    place: { x: 0, y: 0, w: 12, h: 8 },
                    panel: {
                        type: 'chart',
                        config: {
                            query: { language: 'query', query: { series: [] } },
                            viz: { type: 'line' },
                        },
                    },
                },
            ]),
            expected: [{ path: 'tabs[0].tiles[0].panel.config.query', message: expect.any(String) }],
        },
        {
            name: 'two chart targets with the same refId',
            document: withTiles([
                {
                    id: 'a',
                    place: { x: 0, y: 0, w: 12, h: 8 },
                    panel: {
                        type: 'chart',
                        config: {
                            targets: [
                                { refId: 'A', query: { language: 'hogql', query: 'select 1' } },
                                { refId: 'A', query: { language: 'hogql', query: 'select 2' } },
                            ],
                            viz: { type: 'line' },
                        },
                    },
                },
            ]),
            expected: [{ path: 'tabs[0].tiles[0].panel.config.targets', message: expect.any(String) }],
        },
        {
            name: 'a chart type the host does not offer',
            document: withTiles([
                {
                    id: 'a',
                    place: { x: 0, y: 0, w: 12, h: 8 },
                    panel: {
                        type: 'chart',
                        config: { query: { language: 'hogql', query: 'select 1' }, viz: { type: 'radar' } },
                    },
                },
            ]),
            expected: [{ path: 'tabs[0].tiles[0].panel.config.viz', message: expect.any(String) }],
        },
        {
            name: 'a misspelled config field',
            document: withTiles([
                { id: 'a', place: { x: 0, y: 0, w: 8, h: 4 }, panel: { type: 'markdown', config: { txt: 'hi' } } },
            ]),
            expected: [
                { path: 'tabs[0].tiles[0].panel.config.text', message: expect.any(String) },
                { path: 'tabs[0].tiles[0].panel.config', message: expect.stringContaining('txt') },
            ],
        },
        {
            name: 'a shared panel that carries its own parts',
            document: {
                ...(withTiles([{ id: 'a', place: { x: 0, y: 0, w: 8, h: 4 }, panel: { ref: 'note' } }]) as object),
                panels: { note: { ...note, parts: { header: false } } },
            },
            expected: [{ path: 'panels.note.parts', message: expect.stringContaining('parts') }],
        },
        {
            name: 'a document saved by a newer version',
            document: { ...(withTiles([]) as object), version: 3 },
            expected: [{ path: 'version', message: expect.stringContaining('newer version') }],
        },
        {
            name: 'a tile smaller than its panel allows',
            document: withTiles([{ id: 'a', place: { x: 0, y: 0, w: 1, h: 4 }, panel: note }]),
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
                    panel: {
                        type: 'section',
                        title: 'S',
                        tiles: [{ id: 'a', place: { x: 2, y: 0, w: 6, h: 4 }, panel: note }],
                    },
                },
            ]),
            expected: [
                { path: 'tabs[0].tiles[0].panel.tiles[0].place', message: "The tile goes past the grid's 6 columns" },
            ],
        },
        {
            name: 'sections nested deeper than the limit',
            document: withTiles([nestedSections(MAX_SECTION_DEPTH + 1)]),
            expected: [
                {
                    path: `tabs[0].tiles[0]${'.panel.tiles[0]'.repeat(MAX_SECTION_DEPTH)}.panel`,
                    message: `Sections nest at most ${MAX_SECTION_DEPTH} deep`,
                },
            ],
        },
        {
            name: 'two tiles with one id',
            document: withTiles([
                { id: 'a', place: { x: 0, y: 0, w: 8, h: 4 }, panel: note },
                { id: 'a', place: { x: 8, y: 0, w: 8, h: 4 }, panel: note },
            ]),
            expected: [{ path: 'tabs[0].tiles[1].id', message: 'The id "a" is used by another tile or tab' }],
        },
        {
            name: 'a filter of a kind the host does not support, and one missing its config',
            document: {
                ...(withTiles([]) as object),
                filters: [
                    { id: 'a', type: 'country-map', config: {} },
                    { id: 'b', type: 'select', config: { key: '$browser' } },
                ],
            },
            expected: [
                {
                    path: 'filters[0].type',
                    message: 'Unknown filter type "country-map". Known types: select, property',
                },
                { path: 'filters[1].config.options', message: expect.any(String) },
            ],
        },
        {
            name: 'two filters on the same field',
            document: {
                ...(withTiles([]) as object),
                filters: [
                    { id: 'a', type: 'select', config: { key: '$browser', options: ['Chrome'] } },
                    { id: 'b', type: 'select', config: { key: '$browser', options: ['Safari'] } },
                ],
            },
            expected: [{ path: 'filters[1]', message: 'Another filter already narrows this field' }],
        },
        {
            name: 'a time range the picker cannot read',
            document: { ...(withTiles([]) as object), time: { from: 'now-7days', to: 'now' } },
            expected: [{ path: 'time.from', message: expect.any(String) }],
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
        expect(validateDashboard(document, SPECS, FILTER_SPECS)).toEqual(expected)
    })

    it('accepts fields a newer version added', () => {
        const document = {
            ...(withTiles([
                { id: 'a', place: { x: 0, y: 0, w: 8, h: 4 }, panel: { ...note, pinned: true }, locked: true },
            ]) as object),
            tags: ['growth'],
            folder: 'Team',
            owner: 'someone',
        }

        expect(validateDashboard(document, SPECS, FILTER_SPECS)).toEqual([])
    })

    it('keeps the section type out of content panels when the schema parses a document on its own', () => {
        const document = withTiles([
            { id: 'a', place: { x: 0, y: 0, w: 6, h: 4 }, panel: { type: 'section', config: {} } },
        ])

        expect(dashboardSchema.safeParse(document).success).toBe(false)
    })
})
