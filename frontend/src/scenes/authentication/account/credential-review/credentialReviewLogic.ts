import { actions, afterMount, connect, kea, listeners, path } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { passkeySettingsLogic } from 'scenes/settings/user/passkeySettingsLogic'
import { personalAPIKeysLogic } from 'scenes/settings/user/personalAPIKeysLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { credentialReviewLogicType } from './credentialReviewLogicType'

export const credentialReviewLogic = kea<credentialReviewLogicType>([
    path(['scenes', 'authentication', 'account', 'credential-review', 'credentialReviewLogic']),
    // connect (not bare import calls) so both list logics are mounted as dependencies
    // of this scene logic. afterMount runs before the review component renders, so without
    // this the load calls below hit an unmounted logic and throw, which sceneLogic
    // catches and turns into a 404 for the whole credential review screen.
    connect(() => ({
        actions: [personalAPIKeysLogic, ['loadKeys'], passkeySettingsLogic, ['loadPasskeys']],
    })),
    actions({
        markComplete: true,
    }),
    listeners({
        markComplete: async () => {
            try {
                await api.create('api/users/@me/credentials_review_complete/')
            } catch {
                lemonToast.error('Could not save your review. Try again.')
                return
            }
            // Flip the local user state's requires_credential_review via reducer before
            // navigating: a stale in-flight loadUser response would otherwise re-trigger
            // the post-login redirect from userLogic.loadUserSuccess.
            userLogic.actions.credentialReviewDismissed()
            userLogic.actions.loadUser()
            router.actions.push(urls.projectHomepage())
        },
    }),
    afterMount(({ actions }) => {
        // Neither logic auto-loads its list on mount, so trigger both here. Otherwise
        // the review screen would render empty until the user hit the settings page.
        actions.loadKeys()
        actions.loadPasskeys()
    }),
])
