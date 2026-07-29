import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { healthSceneLogic } from './healthSceneLogic'

describe('healthSceneLogic', () => {
    let logic: ReturnType<typeof healthSceneLogic.build>
    let getSpy: jest.SpyInstance
    let createSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        getSpy = jest.spyOn(api, 'get').mockResolvedValue({ results: [], count: 0 })
        createSpy = jest.spyOn(api, 'create').mockResolvedValue({ scheduled_kinds: [], kinds_failed: [], team_id: 1 })
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('loads issues on mount without auto-firing the throttled refresh endpoint', async () => {
        logic = healthSceneLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadHealthIssuesSuccess'])

        expect(getSpy).toHaveBeenCalled()
        // The refresh POST is throttled to one call per team every 5 minutes and checks re-run on a
        // daily schedule, so mounting must not auto-fire it — that was the source of the 429 storm.
        expect(createSpy).not.toHaveBeenCalled()
    })

    it('fires the refresh endpoint only when the user explicitly refreshes', async () => {
        logic = healthSceneLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadHealthIssuesSuccess'])

        logic.actions.refreshHealthData()

        // setNextRefreshAvailableAt only fires after the refresh POST resolves.
        await expectLogic(logic).toDispatchActions(['refreshHealthData', 'setNextRefreshAvailableAt'])
        expect(createSpy).toHaveBeenCalledTimes(1)
        expect(String(createSpy.mock.calls[0][0])).toContain('health_issues/refresh/')
    })
})
