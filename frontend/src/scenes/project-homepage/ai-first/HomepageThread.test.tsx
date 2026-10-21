import { act, cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'
import { Suspense } from 'react'

import { maxLogic } from 'scenes/max/maxLogic'
import { maxMocks } from 'scenes/max/testUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { aiFirstHomepageLogic } from './aiFirstHomepageLogic'
import { HOMEPAGE_TAB_ID } from './constants'
import { HomepageThread } from './HomepageThread'

let mockThreadLoading = false
const mockPendingThread = new Promise<void>(() => {})

jest.mock('scenes/max/Thread', () => ({
    Thread: () => {
        if (mockThreadLoading) {
            throw mockPendingThread
        }
        return <div data-attr="mock-thread" />
    },
}))

describe('HomepageThread', () => {
    const QUERY = 'why did signups drop'

    let homepageLogic: ReturnType<typeof aiFirstHomepageLogic.build>
    let maxLogicInstance: ReturnType<typeof maxLogic.build>

    beforeEach(() => {
        mockThreadLoading = false
        useMocks({
            ...maxMocks,
            get: {
                ...maxMocks.get,
                '/api/projects/:team_id/dashboards/': { results: [] },
                '/api/projects/:team_id/file_system/': { results: [] },
                '/api/projects/:team_id/file_system_shortcut/': { results: [] },
            },
        })
        initKeaTests()
        jest.useFakeTimers()

        maxLogicInstance = maxLogic({ panelId: HOMEPAGE_TAB_ID })
        maxLogicInstance.mount()
        homepageLogic = aiFirstHomepageLogic()
        homepageLogic.mount()
        homepageLogic.actions.setQuery(QUERY)
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
        jest.restoreAllMocks()
        homepageLogic.unmount()
        maxLogicInstance.unmount()
    })

    // The send waits 100 ms so the thread logic is mounted first. Without cleanup on the effect, a
    // navigation away inside that window still starts a conversation the user has already left.
    it.each([
        ['sends the initial query once the delay passes', false, false, 1],
        ['drops the send when the thread unmounts first', false, true, 0],
        ['sends while the thread UI loads', true, false, 1],
        ['drops the pending send when the loading thread unmounts', true, true, 0],
    ])('%s', (_case, threadLoading, unmountBeforeSend, expectedCalls) => {
        mockThreadLoading = threadLoading
        const askMax = jest
            .spyOn(maxLogicInstance.actions, 'askMax')
            .mockImplementation((prompt) => ({ prompt, addToThread: true, uiContext: undefined }))

        const { unmount } = render(
            <Provider>
                <Suspense fallback={null}>
                    <HomepageThread />
                </Suspense>
            </Provider>
        )
        if (unmountBeforeSend) {
            unmount()
        }
        act(() => {
            jest.advanceTimersByTime(100)
        })

        expect(askMax).toHaveBeenCalledTimes(expectedCalls)
    })
})
