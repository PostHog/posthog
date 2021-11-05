import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'

global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
    } as any as Response)
)

describe('toolbar toolbarLogic', () => {
    let logic: ReturnType<typeof toolbarLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = toolbarLogic({ apiURL: 'http://localhost' })
        logic.mount()
    })

    it('mounts feature flags', () => {
        expectLogic(logic).toMount([featureFlagsLogic])
    })
})
