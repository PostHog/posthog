import { actions, afterMount, connect, kea, listeners, path } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { personalAPIKeysLogic } from 'scenes/settings/user/personalAPIKeysLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { credentialReviewLogicType } from './credentialReviewLogicType'

export const credentialReviewLogic = kea<credentialReviewLogicType>([
    path(['scenes', 'authentication', 'credentialReviewLogic']),
    // connect (not a bare import call) so personalAPIKeysLogic is mounted as a dependency
    // of this scene logic. afterMount runs before the review component renders, so without
    // this the loadKeys() call below hits an unmounted logic and throws, which sceneLogic
    // catches and turns into a 404 for the whole credential review screen.
    connect(() => ({
        actions: [personalAPIKeysLogic, ['loadKeys']],
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
        // personalAPIKeysLogic only auto-loads teams (not keys) when it mounts; the
        // settings page calls loadKeys() from its own useEffect. Trigger it here so the
        // review table isn't dismissable while empty.
        actions.loadKeys()
    }),
])
