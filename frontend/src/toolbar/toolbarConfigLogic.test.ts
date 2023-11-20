import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'

global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
    } as any as Response)
)

describe('toolbar toolbarLogic', () => {
    let logic: ReturnType<typeof toolbarConfigLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = toolbarConfigLogic({ apiURL: 'http://localhost' })
        logic.mount()
    })

    it('is not authenticated', () => {
        expectLogic(logic).toMatchValues({ isAuthenticated: false })
    })
})
