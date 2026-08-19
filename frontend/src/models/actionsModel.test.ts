import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { actionsModel } from './actionsModel'

describe('actionsModel', () => {
    let logic: ReturnType<typeof actionsModel.build>
    let lastRequestUrl: URL | undefined

    beforeEach(() => {
        lastRequestUrl = undefined
        useMocks({
            get: {
                '/api/projects/:team/actions/': ({ request }) => {
                    lastRequestUrl = new URL(request.url)
                    return [200, { count: 0, results: [] }]
                },
            },
        })
        initKeaTests()
        logic = actionsModel()
        logic.mount()
    })

    // The model is permanently mounted and reloads on every authenticated page load. Without a
    // bound it requests every action each time, which is what overloaded the endpoint. This locks
    // the default request to a limit so a removed bound fails here.
    it('bounds the default load with a limit', async () => {
        await expectLogic(logic).toDispatchActions(['loadActions', 'loadActionsSuccess'])
        expect(lastRequestUrl?.searchParams.get('limit')).toEqual('1000')
    })
})
