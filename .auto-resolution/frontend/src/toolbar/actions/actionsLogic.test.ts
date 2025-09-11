import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { ActionType } from '~/types'

const unsortedActions: ActionType[] = [
    { name: 'zoo', created_at: '', created_by: null, id: 1, pinned_at: null },
    { name: 'middle', created_at: '', created_by: null, id: 2, pinned_at: null },
    { name: 'begin', created_at: '', created_by: null, id: 3, pinned_at: null },
]
const apiJson = { results: unsortedActions }

global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        json: () => Promise.resolve(apiJson),
    } as any as Response)
)

describe('toolbar actionsLogic', () => {
    let logic: ReturnType<typeof actionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        toolbarConfigLogic({ apiURL: 'http://localhost' }).mount()
        logic = actionsLogic()
        logic.mount()
    })

    it('has expected defaults', () => {
        expectLogic(logic).toMatchValues({
            sortedActions: [],
            searchTerm: '',
            allActions: [],
            actionCount: 0,
        })
    })

    it('can get actions', async () => {
        await expectLogic(logic, () => {
            logic.actions.getActions()
        })
            .delay(0)
            .toMatchValues({
                sortedActions: [
                    { created_at: '', created_by: null, id: 3, name: 'begin', pinned_at: null },
                    { created_at: '', created_by: null, id: 2, name: 'middle', pinned_at: null },
                    { created_at: '', created_by: null, id: 1, name: 'zoo', pinned_at: null },
                ],
                actionCount: 3,
                allActions: apiJson.results,
            })
    })

    it('can filter the actions', async () => {
        await expectLogic(logic, () => {
            logic.actions.getActions()
            logic.actions.setSearchTerm('i')
        })
            .delay(0)
            .toMatchValues({
                sortedActions: [
                    { created_at: '', created_by: null, id: 3, name: 'begin', pinned_at: null },
                    { created_at: '', created_by: null, id: 2, name: 'middle', pinned_at: null },
                ],
            })
    })
})
