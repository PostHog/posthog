import { getContext } from 'kea'
import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { NEW_INTERNAL_TAB, newInternalTab } from './newInternalTab'

describe('newInternalTab', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('falls back to router.actions.push when sceneLogic is not mounted', () => {
        const pushSpy = jest.spyOn(router.actions, 'push')
        const path = '/replay/abc123?timestamp=1700000000000'

        newInternalTab(path)

        expect(pushSpy).toHaveBeenCalledWith(path)
    })

    it('does nothing when called with no path and sceneLogic is not mounted', () => {
        const pushSpy = jest.spyOn(router.actions, 'push')

        newInternalTab()

        expect(pushSpy).not.toHaveBeenCalled()
    })

    it('dispatches NEW_INTERNAL_TAB instead of pushing when sceneLogic is mounted', () => {
        const store = getContext().store
        // Simulate sceneLogic being mounted by populating its reducer slot in the store state.
        // This avoids the heavyweight setup of actually mounting sceneLogic in this unit test
        // while still exercising the gating logic in newInternalTab.
        const originalGetState = store.getState.bind(store)
        jest.spyOn(store, 'getState').mockImplementation(() => {
            const state = originalGetState() as Record<string, any>
            return {
                ...state,
                scenes: { ...state.scenes, sceneLogic: { tabs: [] } },
            }
        })

        const dispatchSpy = jest.spyOn(store, 'dispatch')
        const pushSpy = jest.spyOn(router.actions, 'push')
        const path = '/replay/abc123'

        newInternalTab(path)

        expect(dispatchSpy).toHaveBeenCalledWith(
            expect.objectContaining({
                type: NEW_INTERNAL_TAB,
                payload: { path, source: 'internal_link' },
            })
        )
        expect(pushSpy).not.toHaveBeenCalled()
    })
})
