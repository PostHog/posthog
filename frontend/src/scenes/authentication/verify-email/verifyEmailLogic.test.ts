import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { verifyEmailLogic } from './verifyEmailLogic'

describe('verifyEmailLogic', () => {
    let logic: ReturnType<typeof verifyEmailLogic.build>
    let originalAppContext: AppContext | undefined

    beforeEach(() => {
        originalAppContext = window.POSTHOG_APP_CONTEXT
    })

    afterEach(() => {
        logic.unmount()
        window.POSTHOG_APP_CONTEXT = originalAppContext
    })

    const mountWithUser = (currentUser: Record<string, any> | null): void => {
        window.POSTHOG_APP_CONTEXT = { ...originalAppContext, current_user: currentUser } as unknown as AppContext
        initKeaTests()
        logic = verifyEmailLogic()
        logic.mount()
    }

    it('takes the uuid from the route', () => {
        mountWithUser({ uuid: 'user-uuid' })
        router.actions.push(urls.verifyEmail('route-uuid'))

        expect(logic.values.uuid).toEqual('route-uuid')
        expect(logic.values.view).toEqual('pending')
    })

    // In-app entry points have no uuid to put in the path, so a bare /verify_email must still know
    // who to verify for a signed-in user.
    it('falls back to the signed-in user on the bare route', () => {
        mountWithUser({ uuid: 'user-uuid' })
        router.actions.push(urls.verifyEmail())

        expect(logic.values.uuid).toEqual('user-uuid')
        expect(logic.values.view).toEqual('pending')
    })

    it('has nothing to verify on the bare route without a user', () => {
        mountWithUser(null)
        router.actions.push(urls.verifyEmail())

        expect(logic.values.uuid).toBeNull()
        expect(logic.values.view).toEqual('invalid')
    })
})
