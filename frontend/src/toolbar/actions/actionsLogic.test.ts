import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { ActionType } from '~/types'

const unsortedActions: ActionType[] = [
    { name: 'zoo', created_at: '', created_by: null, id: 1 },
    { name: 'middle', created_at: '', created_by: null, id: 2 },
    { name: 'begin', created_at: '', created_by: null, id: 3 },
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

    initKeaTestLogic()

    beforeEach(() => {
        toolbarLogic({ apiURL: 'http://localhost' }).mount()
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
                    { created_at: '', created_by: null, id: 3, name: 'begin' },
                    { created_at: '', created_by: null, id: 2, name: 'middle' },
                    { created_at: '', created_by: null, id: 1, name: 'zoo' },
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
                    { created_at: '', created_by: null, id: 3, name: 'begin' },
                    { created_at: '', created_by: null, id: 2, name: 'middle' },
                ],
            })
    })
})
