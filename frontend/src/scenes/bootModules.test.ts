import { earlyUserContextReads, watchEarlyUserContextReads } from 'lib/utils/deferredAppContext'

import type { AppContext } from '~/types'

describe('app boot modules', () => {
    afterEach(() => {
        delete window.POSTHOG_APP_CONTEXT
        delete window.POSTHOG_APP_CONTEXT_REQUEST
    })

    it('do not read the user data when they load', async () => {
        window.POSTHOG_APP_CONTEXT_REQUEST = new Promise(() => {})
        window.POSTHOG_APP_CONTEXT = { anonymous: false, deferred: true } as unknown as AppContext
        watchEarlyUserContextReads()

        await jest.isolateModulesAsync(async () => {
            await import('scenes/App')
            await import('scenes/bootApp')
        })

        expect(earlyUserContextReads()).toEqual([])
    })
})
