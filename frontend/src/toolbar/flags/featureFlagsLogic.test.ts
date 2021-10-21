import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
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

global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        json: () => Promise.resolve(featureFlags),
    } as any as Response)
)

describe('feature flags logic', () => {
    let logic: ReturnType<typeof featureFlagsLogic.build>

    initKeaTestLogic()

    beforeEach(() => {
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
})
