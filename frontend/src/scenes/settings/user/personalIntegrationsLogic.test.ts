import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { personalIntegrationsLogic } from './personalIntegrationsLogic'

describe('personalIntegrationsLogic', () => {
    let logic: ReturnType<typeof personalIntegrationsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/users/@me/integrations/': () => [200, { results: [] }],
                '/api/users/@me/integrations/slack/linkable_workspaces/': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        logic = personalIntegrationsLogic()
    })

    afterEach(() => {
        jest.useRealTimers()
        logic.unmount()
    })

    it('refreshes on an interval only while a section is subscribed, and stops with the last one', async () => {
        jest.useFakeTimers()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadIntegrationsSuccess'])

        logic.actions.startPolling()
        logic.actions.startPolling()
        expect(logic.cache.disposables.registry.has('poll')).toBe(true)

        await expectLogic(logic, () => {
            jest.advanceTimersByTime(30_000)
        }).toDispatchActions(['loadIntegrations'])

        logic.actions.stopPolling()
        expect(logic.cache.disposables.registry.has('poll')).toBe(true)
        logic.actions.stopPolling()
        expect(logic.cache.disposables.registry.has('poll')).toBe(false)
    })
})
