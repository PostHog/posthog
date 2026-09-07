import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CustomerProfileConfigType, CustomerProfileScope } from '~/types'

import { customerProfileLogic } from './customerProfileLogic'

const CONFIGS_URL = '/api/environments/:team_id/customer_profile_configs/'

const savedConfig = (content: CustomerProfileConfigType['content']): CustomerProfileConfigType => ({
    id: 'config-person',
    team: 997,
    content,
    sidebar: [],
    pinned_properties: [],
    scope: CustomerProfileScope.PERSON,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
})

const mocksFor = (content: CustomerProfileConfigType['content']): Parameters<typeof useMocks>[0] => ({
    get: { [CONFIGS_URL]: () => ({ count: 1, results: [savedConfig(content)] }) },
})

type BuiltLogic = ReturnType<typeof customerProfileLogic.build>

describe('customerProfileLogic', () => {
    let logic: BuiltLogic

    const mount = async (): Promise<BuiltLogic> => {
        logic = customerProfileLogic({
            scope: CustomerProfileScope.PERSON,
            attrs: { personId: 'person-1' },
            key: 'test',
            canvasShortId: 'test-canvas',
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        return logic
    }

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.CUSTOMER_PROFILE_CONFIG_BUTTON], {
            [FEATURE_FLAGS.CUSTOMER_PROFILE_CONFIG_BUTTON]: true,
        })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('keeps a saved layout that has every tile turned off', async () => {
        useMocks(mocksFor([]))
        await mount()

        expect(logic.values.storedContent).toEqual([])
        expect(logic.values.content).toEqual([])
    })

    it('shows the default layout for a config saved for its pinned properties alone', async () => {
        useMocks(mocksFor({}))
        await mount()

        expect(logic.values.storedContent).toBeNull()
        expect(logic.values.content).toEqual(logic.values.defaultContent)
    })
})
