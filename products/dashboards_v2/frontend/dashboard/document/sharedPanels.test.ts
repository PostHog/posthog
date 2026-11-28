import type { DashboardDocument } from './dashboardTypes'
import { loadDashboard, saveDashboard } from './sharedPanels'
import { everyTile } from './tileTree'

const HOST_FIELD = { pinned: true }

describe('sharedPanels', () => {
    it('leaves out a panel that nests tiles without being a section, however deep, without walking them', () => {
        let nested: unknown = { type: 'markdown', config: { text: 'deep' } }
        for (let depth = 0; depth < 100_000; depth++) {
            nested = { type: 'markdown', config: { text: 'deep' }, tiles: [{ id: 't', place: {}, panel: nested }] }
        }
        const document = {
            version: 2,
            title: 'Hostile',
            tabs: [{ id: 'one', title: 'One', tiles: [{ id: 'a', place: { x: 0, y: 0, w: 8, h: 8 }, panel: nested }] }],
        } as DashboardDocument

        const [tab] = loadDashboard(document).tabs
        expect('tiles' in tab && everyTile(tab.tiles).map((tile) => tile.id)).toEqual([])
    })

    it('leaves out a tile whose shared panel is a section', () => {
        const document = {
            version: 2,
            title: 'Hostile',
            panels: { s: { type: 'section', title: 's', tiles: [] } },
            tabs: [
                {
                    id: 'one',
                    title: 'One',
                    tiles: [{ id: 'a', place: { x: 0, y: 0, w: 8, h: 8 }, panel: { ref: 's' } }],
                },
            ],
        } as unknown as DashboardDocument

        const [tab] = loadDashboard(document).tabs
        expect('tiles' in tab && tab.tiles).toEqual([])
    })

    it.each(['signups', 'constructor', '__proto__'])(
        "loads a shared panel onto each tile with that tile's own parts, and saves it back once (ref %s)",
        (ref) => {
            const document: DashboardDocument = {
                version: 2,
                title: 'Test',
                panels: { [ref]: { type: 'markdown', title: 'Signups', config: { text: 'hi' } } },
                tabs: [
                    {
                        id: 'one',
                        title: 'One',
                        tiles: [
                            {
                                id: 'a',
                                place: { x: 0, y: 0, w: 8, h: 8 },
                                // A field the host added, such as the boards API's, that each tile keeps for itself.
                                panel: { ref, parts: { header: false }, ...HOST_FIELD },
                            },
                        ],
                    },
                    {
                        id: 'two',
                        title: 'Two',
                        tiles: [
                            {
                                id: 's',
                                place: { x: 0, y: 0, w: 24, h: 10 },
                                panel: {
                                    type: 'section',
                                    title: 'Section',
                                    tiles: [{ id: 'b', place: { x: 0, y: 0, w: 24, h: 8 }, panel: { ref } }],
                                },
                            },
                        ],
                    },
                ],
            }
            const loaded = loadDashboard(document)
            expect(
                loaded.tabs.flatMap((tab) => ('tiles' in tab ? everyTile(tab.tiles) : [])).map((tile) => tile.panel)
            ).toEqual([
                {
                    type: 'markdown',
                    title: 'Signups',
                    config: { text: 'hi' },
                    ref,
                    parts: { header: false },
                    pinned: true,
                },
                expect.objectContaining({ type: 'section' }),
                { type: 'markdown', title: 'Signups', config: { text: 'hi' }, ref },
            ])
            expect(saveDashboard(loaded)).toEqual(document)
        }
    )

    it('leaves out a tile whose shared panel is missing', () => {
        const document: DashboardDocument = {
            version: 2,
            title: 'Test',
            tabs: [
                {
                    id: 'one',
                    title: 'One',
                    tiles: [{ id: 'a', place: { x: 0, y: 0, w: 8, h: 8 }, panel: { ref: 'gone' } }],
                },
            ],
        }
        expect(loadDashboard(document).tabs[0]).toEqual({ id: 'one', title: 'One', tiles: [] })
    })
})
