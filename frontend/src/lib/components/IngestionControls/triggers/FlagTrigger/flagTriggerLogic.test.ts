import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { flagTriggerLogic } from './flagTriggerLogic'

describe('flagTriggerLogic', () => {
    let logic: ReturnType<typeof flagTriggerLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    it('degrades to no flag when the linked flag was deleted, instead of throwing on mount', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/999/`]: () => [404, { detail: 'Not found.' }],
            },
        })
        initKeaTests()

        logic = flagTriggerLogic({
            logicKey: 'test',
            flag: { id: 999, key: 'gone', variant: null },
            onChange: () => {},
        })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadFeatureFlag', 'loadFeatureFlagSuccess']).toFinishAllListeners()

        expect(logic.values.featureFlag).toBeNull()
        expect(logic.values.linkedFlag).toBeNull()
    })
})
