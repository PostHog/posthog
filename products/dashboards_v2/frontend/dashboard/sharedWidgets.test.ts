import type { DashboardDocument } from './dashboardTypes'
import { loadDashboard, saveDashboard } from './sharedWidgets'
import { everyTile } from './tileTree'

describe('sharedWidgets', () => {
    it.each(['signups', 'constructor', '__proto__'])(
        "loads a shared widget onto each tile with that tile's own parts, and saves it back once (ref %s)",
        (ref) => {
            const document: DashboardDocument = {
                version: 2,
                title: 'Test',
                widgets: { [ref]: { type: 'markdown', title: 'Signups', config: { text: 'hi' } } },
                tabs: [
                    {
                        id: 'one',
                        title: 'One',
                        tiles: [
                            {
                                id: 'a',
                                place: { x: 0, y: 0, w: 8, h: 8 },
                                widget: { ref, parts: { header: false } },
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
                                widget: {
                                    type: 'section',
                                    title: 'Section',
                                    tiles: [{ id: 'b', place: { x: 0, y: 0, w: 24, h: 8 }, widget: { ref } }],
                                },
                            },
                        ],
                    },
                ],
            }
            const loaded = loadDashboard(document)
            expect(
                loaded.tabs.flatMap((tab) => ('tiles' in tab ? everyTile(tab.tiles) : [])).map((tile) => tile.widget)
            ).toEqual([
                { type: 'markdown', title: 'Signups', config: { text: 'hi' }, ref, parts: { header: false } },
                expect.objectContaining({ type: 'section' }),
                { type: 'markdown', title: 'Signups', config: { text: 'hi' }, ref },
            ])
            expect(saveDashboard(loaded)).toEqual(document)
        }
    )

    it('leaves out a tile whose shared widget is missing', () => {
        const document: DashboardDocument = {
            version: 2,
            title: 'Test',
            tabs: [
                {
                    id: 'one',
                    title: 'One',
                    tiles: [{ id: 'a', place: { x: 0, y: 0, w: 8, h: 8 }, widget: { ref: 'gone' } }],
                },
            ],
        }
        expect(loadDashboard(document).tabs[0]).toEqual({ id: 'one', title: 'One', tiles: [] })
    })
})
