import type { Dashboard, Tile } from '../../dashboard/document/dashboardTypes'
import { findTile } from '../../dashboard/document/tileTree'
import { everyTile } from '../../dashboard/document/tileTree'
import { type PresentationEdit, applyPresentationEdit } from '../../dashboard/edits/presentationEdits'
import type { MenuAction } from '../../menu/menuAction'
import { DEFAULT_PANELS } from '../../panels/defaultPanels'
import { backgroundColorAction, showAction } from './appearanceActions'

const text = (id: string): Tile => ({
    id,
    place: { x: 0, y: 0, w: 8, h: 8 },
    panel: { type: 'markdown', title: id, config: { text: id } },
})

describe('showAction', () => {
    it('sets a setting on every tile of the tab it applies to, inside sections too, and nowhere else', () => {
        const section: Tile = {
            id: 's',
            place: { x: 0, y: 8, w: 24, h: 10 },
            panel: { type: 'section', title: 's', tiles: [text('inner')] },
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
        expect(findTile(board, 'inner')?.panel).toMatchObject({
            parts: { header: false },
            appearance: { border: false },
        })
        expect(findTile(board, 's')?.panel).toMatchObject({ appearance: { border: false } })
        expect(findTile(board, 's')?.panel).not.toHaveProperty('parts')
        expect(findTile(board, 'other')?.panel).not.toHaveProperty('appearance')
    })

    it('tints a tile and clears the tint again, ticking the current color', () => {
        let board: Dashboard = { version: 2, title: 'Test', tabs: [{ id: 'tab', title: 'Tab', tiles: [text('a')] }] }
        const pick = (color: string): MenuAction => {
            const tile = findTile(board, 'a')!
            const menu = { key: 'background-color', label: 'Background color', dataAttr: 'background-color' }
            const action = backgroundColorAction(menu, [tile], DEFAULT_PANELS, null, (edit: PresentationEdit) => {
                board = applyPresentationEdit(board, edit)
            })
            return action!.submenu!.find((item) => item.key === color)!
        }

        pick('blue').onSelect!()
        expect(pick('blue').checked).toBe(true)
        expect(findTile(board, 'a')?.panel).toMatchObject({ appearance: { backgroundColor: 'var(--color-blue-500)' } })

        pick('default').onSelect!()
        expect(pick('default').checked).toBe(true)
        expect(findTile(board, 'a')?.panel.appearance).not.toHaveProperty('backgroundColor')
    })
})
