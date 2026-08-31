import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { filterTestAccountsDefaultsLogic } from './filterTestAccountDefaultsLogic'

describe('filterTestAccountsDefaultsLogic', () => {
    let logic: ReturnType<typeof filterTestAccountsDefaultsLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('mounts without throwing when localStorage reads are blocked', async () => {
        // Firefox with storage denied throws NS_ERROR_FAILURE on every access.
        jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
            throw new Error('NS_ERROR_FAILURE')
        })

        logic = filterTestAccountsDefaultsLogic()
        expect(() => logic.mount()).not.toThrow()

        await expectLogic(logic).toMatchValues({ filterTestAccountsDefault: false })
    })

    it('does not throw when a blocked localStorage rejects a write', async () => {
        jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('NS_ERROR_FAILURE')
        })

        logic = filterTestAccountsDefaultsLogic()
        logic.mount()

        await expectLogic(logic, () => {
            expect(() => logic.actions.setLocalDefault(true)).not.toThrow()
        }).toMatchValues({ filterTestAccountsDefault: true })
    })
})
