import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { CombinedFeatureFlagAndValueType } from '~/types'

const featureFlags = [
    { feature_flag: { key: 'flag 1' } },
    { feature_flag: { key: 'flag 2' } },
    { feature_flag: { key: 'flag 3', name: 'mentions 2' } },
] as CombinedFeatureFlagAndValueType[]

const featureFlagsWithExtraInfo = [
    { currentValue: undefined, hasOverride: false, hasVariants: false, feature_flag: { key: 'flag 1' } },
    { currentValue: undefined, hasOverride: false, hasVariants: false, feature_flag: { key: 'flag 2' } },
    {
        currentValue: undefined,
        hasOverride: false,
        hasVariants: false,
        feature_flag: { key: 'flag 3', name: 'mentions 2' },
    },
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
        toolbarConfigLogic({ apiURL: 'http://localhost' }).mount()
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
            filteredFlags: [
                { currentValue: undefined, hasOverride: false, hasVariants: false, feature_flag: { key: 'flag 2' } },
                {
                    currentValue: undefined,
                    feature_flag: {
                        key: 'flag 3',
                        name: 'mentions 2',
                    },
                    hasOverride: false,
                    hasVariants: false,
                },
            ],
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
        }).toDispatchActions([toolbarConfigLogic.actionTypes.tokenExpired])
    })
})
