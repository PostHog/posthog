import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { CombinedFeatureFlagAndOverrideType } from '~/types'

const featureFlags = [
    { feature_flag: { name: 'flag 1' } },
    { feature_flag: { name: 'flag 2' } },
] as CombinedFeatureFlagAndOverrideType[]

const featureFlagsWithExtraInfo = [
    { currentValue: undefined, hasVariants: false, feature_flag: { name: 'flag 1' } },
    { currentValue: undefined, hasVariants: false, feature_flag: { name: 'flag 2' } },
]

describe('toolbar featureFlagsLogic', () => {
    let logic: ReturnType<typeof featureFlagsLogic.build>
    beforeEach(() => {
        global.fetch = jest.fn(() =>
            Promise.resolve({
                ok: true,
                status: 200,
                json: () => Promise.resolve(featureFlags),
            } as any as Response)
        )
    })

    beforeEach(() => {
        initKeaTests()
        toolbarLogic({ apiURL: 'http://localhost' }).mount()
        logic = featureFlagsLogic()
        logic.mount()
    })

    it('has expected defaults', () => {
        expectLogic(logic).toMatchValues({
            userFlags: featureFlags,
            searchTerm: '',
            filteredFlags: featureFlagsWithExtraInfo,
        })
    })

    it('can filter the flags', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('2')
        }).toMatchValues({
            filteredFlags: [{ currentValue: undefined, hasVariants: false, feature_flag: { name: 'flag 2' } }],
        })
    })

    it('expires the token if request failed', async () => {
        global.fetch = jest.fn(() =>
            Promise.resolve({
                ok: false,
                status: 401,
                json: () => Promise.resolve(featureFlags),
            } as any as Response)
        )
        await expectLogic(logic, () => {
            logic.actions.getUserFlags()
        }).toDispatchActions([toolbarLogic.actionTypes.tokenExpired])
    })
})
