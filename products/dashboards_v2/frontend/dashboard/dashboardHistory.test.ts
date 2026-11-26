import { recordEdit, redoEdit, startHistory, undoEdit } from './dashboardHistory'
import type { Dashboard } from './dashboardTypes'

const board = (title: string): Dashboard => ({ version: 2, title, tabs: [{ id: 'tab', title: 'Tab', tiles: [] }] })

describe('dashboardHistory', () => {
    it('adds no undo step and keeps what can be redone when an edit changes nothing', () => {
        const undone = undoEdit(recordEdit(startHistory(board('a')), board('b')))

        expect(recordEdit(undone, board('a'))).toBe(undone)
        expect(redoEdit(undone).present.title).toEqual('b')
    })

    it('undoes and redoes in order, and a new edit clears what could be redone', () => {
        const edited = recordEdit(recordEdit(startHistory(board('a')), board('b')), board('c'))
        const back = undoEdit(undoEdit(edited))

        expect(back.present.title).toEqual('a')
        expect(redoEdit(back).present.title).toEqual('b')
        expect(recordEdit(back, board('d')).future).toEqual([])
    })
})
