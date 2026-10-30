import { AppContext, UserType } from '~/types'

import { applyDeferredAppContext, inlineAppContextUrl } from './deferredAppContext'

describe('deferredAppContext', () => {
    afterEach(() => {
        delete window.POSTHOG_APP_CONTEXT_REQUEST
    })

    it('adds the user data and flags to what the page rendered', async () => {
        window.POSTHOG_APP_CONTEXT = { anonymous: false, deferred: true, current_user: null } as unknown as AppContext
        window.POSTHOG_USER_IDENTITY_WITH_FLAGS = { distinctID: 'page-distinct-id' }
        window.POSTHOG_APP_CONTEXT_REQUEST = Promise.resolve({
            app_context: { current_user: { distinct_id: 'user-1' } as UserType },
            feature_flags: { 'some-flag': true },
        })

        await applyDeferredAppContext()

        expect(window.POSTHOG_APP_CONTEXT).toEqual({
            anonymous: false,
            deferred: true,
            current_user: { distinct_id: 'user-1' },
        })
        expect(window.POSTHOG_USER_IDENTITY_WITH_FLAGS).toEqual({
            distinctID: 'page-distinct-id',
            featureFlags: { 'some-flag': true },
        })
    })

    it.each([
        [
            'https://us.posthog.com/project/1/insights?a=1#tab',
            'https://us.posthog.com/project/1/insights?a=1&deferred_app_context=0#tab',
        ],
        [
            'https://us.posthog.com/project/1?deferred_app_context=1',
            'https://us.posthog.com/project/1?deferred_app_context=0',
        ],
    ])('reloads %s with the user data inline', (href, expected) => {
        expect(inlineAppContextUrl(href)).toEqual(expected)
    })
})
