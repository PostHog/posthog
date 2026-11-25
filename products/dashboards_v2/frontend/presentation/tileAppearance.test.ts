import type { Dashboard, Tile } from '../dashboard/dashboardTypes'
import type { MenuAction } from '../dashboard/menuAction'
import { findTile } from '../dashboard/tileTree'
import { everyTile } from '../dashboard/tileTree'
import { type PresentationEdit, applyPresentationEdit } from './presentationEdits'
import { showAction } from './tileAppearance'

const text = (id: string): Tile => ({
    id,
    place: { x: 0, y: 0, w: 8, h: 8 },
    widget: { type: 'markdown', title: id, config: { text: id } },
})

describe('showAction', () => {
    it('sets a setting on every tile of the tab it applies to, inside sections too, and nowhere else', () => {
        const section: Tile = {
            id: 's',
            place: { x: 0, y: 8, w: 24, h: 10 },
            widget: { type: 'section', title: 's', tiles: [text('inner')] },
        }
        let board: Dashboard = {
            version: 2,
            title: 'Test',
            tabs: [
                { id: 'first', title: 'First', tiles: [text('top'), section] },
                { id: 'second', title: 'Second', tiles: [text('other')] },
            ],
        }
        const pick = (setting: string): MenuAction => {
            const tab = board.tabs[0]
            const menu = { key: 'all', label: 'All tiles', dataAttr: 'all' }
            const tiles = everyTile('tiles' in tab ? tab.tiles : [])
            const action = showAction(menu, tiles, [], null, (edit: PresentationEdit) => {
                board = applyPresentationEdit(board, edit)
            })
            return action!.submenu!.find((item) => item.key === setting)!
        }

        expect(pick('header').checked).toBe(true)
        pick('header').onSelect!()
        pick('border').onSelect!()

        expect(pick('header').checked).toBe(false)
        expect(findTile(board, 'inner')?.widget).toMatchObject({
            parts: { header: false },
            appearance: { border: false },
        })
        expect(findTile(board, 's')?.widget).toMatchObject({ appearance: { border: false } })
        expect(findTile(board, 's')?.widget).not.toHaveProperty('parts')
        expect(findTile(board, 'other')?.widget).not.toHaveProperty('appearance')
    })
})
