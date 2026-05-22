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
    path(['scenes', 'authentication', 'credentialReviewLogic']),
    connect(() => ({
        values: [personalAPIKeysLogic, ['keys', 'keysLoading'], passkeySettingsLogic, ['passkeys', 'passkeysLoading']],
        actions: [
            personalAPIKeysLogic,
            ['loadKeys', 'loadKeysSuccess'],
            passkeySettingsLogic,
            ['loadPasskeys', 'loadPasskeysSuccess'],
        ],
    })),
    actions({
        markComplete: true,
    }),
    listeners(({ actions, values }) => {
        const dismissIfNothingToReview = (): void => {
            // requires_credential_review can be true while both lists come back empty -
            // e.g. user revoked their only credential since loadUser fetched, or the
            // backfill missed them. No partner-issued artifact left to surface, so the
            // screen has nothing to say. Auto-mark reviewed and continue to the app.
            if (
                !values.keysLoading &&
                !values.passkeysLoading &&
                values.keys.length === 0 &&
                values.passkeys.length === 0
            ) {
                actions.markComplete()
            }
        }
        return {
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
            loadKeysSuccess: dismissIfNothingToReview,
            loadPasskeysSuccess: dismissIfNothingToReview,
        }
    }),
    afterMount(({ actions }) => {
        // Neither logic auto-loads its list on mount, so trigger both here. Otherwise
        // the review screen would render empty until the user hit the settings page.
        actions.loadKeys()
        actions.loadPasskeys()
    }),
])
