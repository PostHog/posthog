import { chartSpec } from '../../panels/chart/chartSpec'
import { lineSpec } from '../../panels/chart/viz/line/lineSpec'
import { definePanelSpec } from '../../panels/core/panelSpec'
import { markdownSpec } from '../../panels/markdown/markdownSpec'
import { dashboardFromJson } from './dashboardFromJson'

const SPECS = [definePanelSpec(chartSpec([lineSpec])), definePanelSpec(markdownSpec)]
const tile = (id: string, panel: unknown): unknown => ({ id, place: { x: 0, y: 0, w: 8, h: 4 }, panel })

describe('dashboardFromJson', () => {
    it('loads a document with a broken panel, settled, and reports only that panel', () => {
        const { dashboard, problems } = dashboardFromJson(
            {
                version: 2,
                title: 'From code',
                tabs: [
                    {
                        id: 'tab',
                        title: 'Tab',
                        tiles: [
                            tile('note', { type: 'markdown', config: { text: 'hi' } }),
                            tile('broken', { type: 'markdown', config: {} }),
                        ],
                    },
                ],
            },
            SPECS
        )

        expect(problems.map((problem) => problem.path)).toEqual(['tabs[0].tiles[1].panel.config.text'])
        const tiles = dashboard!.tabs[0] as { tiles: { id: string; place: { y: number } }[] }
        expect(tiles.tiles.map(({ id, place }) => [id, place.y])).toEqual([
            ['note', 0],
            ['broken', 4],
        ])
    })

    it.each([
        ['no tabs', { version: 2, title: 'No tabs' }],
        [
            'a section without tiles',
            {
                version: 2,
                title: 'Empty section',
                tabs: [{ id: 'tab', title: 'Tab', tiles: [tile('s', { type: 'section', title: 'S' })] }],
            },
        ],
    ])('gives no dashboard for a document with %s', (_, json) => {
        const { dashboard, problems } = dashboardFromJson(json, SPECS)

        expect(dashboard).toBeNull()
        expect(problems).not.toEqual([])
    })
})
