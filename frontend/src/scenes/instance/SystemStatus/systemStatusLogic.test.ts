import { expectLogic } from 'kea-test-utils'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { systemStatusLogic } from './systemStatusLogic'

describe('systemStatusLogic', () => {
    let logic: ReturnType<typeof systemStatusLogic.build>
    let patchedKeys: string[]

    beforeEach(() => {
        patchedKeys = []
        initKeaTests()
        eventUsageLogic.mount()
        useMocks({
            get: {
                '/api/instance_status': () => [200, { results: [] }],
                '/api/instance_settings': () => [200, { results: [] }],
            },
            patch: {
                '/api/instance_settings/:key': ({ params }) => {
                    patchedKeys.push(params.key as string)
                    return [200, {}]
                },
            },
        })
        logic = systemStatusLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('saves the email password after the mail host, so the host change cannot clear it', async () => {
        logic.actions.updateInstanceConfigValue('EMAIL_HOST_PASSWORD', 'new-password')
        logic.actions.updateInstanceConfigValue('EMAIL_HOST', 'smtp.elsewhere.example.com')
        logic.actions.saveInstanceConfig()

        await expectLogic(logic).toDispatchActions([
            'increaseUpdatedInstanceConfigCount',
            'increaseUpdatedInstanceConfigCount',
        ])

        expect(patchedKeys).toEqual(['EMAIL_HOST', 'EMAIL_HOST_PASSWORD'])
    })
})
