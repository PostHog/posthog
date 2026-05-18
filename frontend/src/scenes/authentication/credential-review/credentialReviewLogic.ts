import { actions, kea, listeners, path } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { credentialReviewLogicType } from './credentialReviewLogicType'

export const credentialReviewLogic = kea<credentialReviewLogicType>([
    path(['scenes', 'authentication', 'credentialReviewLogic']),
    actions({
        markComplete: true,
    }),
    listeners({
        markComplete: async () => {
            try {
                await api.create('api/users/@me/credentials_review_complete/')
                userLogic.actions.loadUser()
            } catch {
                lemonToast.error('Could not save your review. Try again.')
                return
            }
            router.actions.push(urls.projectHomepage())
        },
    }),
])
