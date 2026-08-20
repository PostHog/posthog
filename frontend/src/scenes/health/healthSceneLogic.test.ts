import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

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

    it('shows an error toast when loading issues fails', async () => {
        getSpy.mockRejectedValue(new Error('Failed to fetch'))
        const errorToastSpy = jest.spyOn(lemonToast, 'error')

        logic = healthSceneLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadHealthIssuesFailure'])

        expect(errorToastSpy).toHaveBeenCalledWith('Failed to load health issues')
    })
})
