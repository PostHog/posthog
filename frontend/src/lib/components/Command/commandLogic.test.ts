import { initKeaTests } from '~/test/init'

import { commandLogic, type CommandHistoryItem } from './commandLogic'

const historyItem = (id: string): CommandHistoryItem => ({
    id,
    name: id,
    href: `/${id}`,
    teamId: 1,
})

describe('commandLogic', () => {
    let logic: ReturnType<typeof commandLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests(false)
        logic = commandLogic.build()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('keeps the five most recently selected command items without duplicates', () => {
        for (const id of ['first', 'second', 'third', 'fourth', 'fifth', 'sixth']) {
            logic.actions.recordCommandSelection(historyItem(id))
        }
        logic.actions.recordCommandSelection(historyItem('fourth'))

        expect(logic.values.commandHistory.map((item) => item.id)).toEqual([
            'fourth',
            'sixth',
            'fifth',
            'third',
            'second',
        ])
    })
})
