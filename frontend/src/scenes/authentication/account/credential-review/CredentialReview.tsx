import { useActions, useValues } from 'kea'

import * as heartPng from '@posthog/brand/hoggies/png/heart'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { SceneExport } from 'scenes/sceneTypes'

import { credentialReviewLogic } from './credentialReviewLogic'
import { CredentialsReviewList } from './CredentialsReviewList'

export const scene: SceneExport = {
    component: CredentialReview,
    logic: credentialReviewLogic,
}

const HedgehogHeart = pngHoggie(heartPng)

export function CredentialReview(): JSX.Element {
    const { markComplete } = useActions(credentialReviewLogic)
    const { continueDisabledReason, isCompleting } = useValues(credentialReviewLogic)

    return (
        <AuthScene notes={AUTH_NOTES.credentialReview.default} wide>
            <AuthSceneCard>
                <div className="max-w-40 mx-auto mb-4">
                    <HedgehogHeart className="w-full h-full" />
                </div>
                <AuthCardTitle
                    title="One more thing"
                    sub="Your account was set up with the credentials and connected apps below. Review them and revoke anything you don't recognize before continuing."
                />
                <div className="mb-6 text-left">
                    <CredentialsReviewList />
                </div>
                <LemonButton
                    type="primary"
                    size="large"
                    fullWidth
                    center
                    onClick={() => markComplete()}
                    loading={isCompleting}
                    disabledReason={continueDisabledReason}
                    data-attr="credential-review-continue"
                >
                    Continue to PostHog
                </LemonButton>
            </AuthSceneCard>
        </AuthScene>
    )
}
