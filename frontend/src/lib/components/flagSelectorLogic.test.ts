import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { flagSelectorLogic } from './flagSelectorLogic'

describe('flagSelectorLogic', () => {
    test.each([
        ['labels the button with the stored flag key', 200, 'checkout-redesign'],
        ['leaves the label to the fallbacks when the lookup fails', 403, ''],
    ])('%s', async (_name: string, status: number, expectedKey: string) => {
        useMocks({
            get: {
                '/api/projects/:team_id/feature_flags/:id/': () => [status, { id: 7, key: 'checkout-redesign' }],
            },
        })
        initKeaTests()
        const logic = flagSelectorLogic({ id: 7 })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ flagKey: expectedKey })

        logic.unmount()
    })
})
