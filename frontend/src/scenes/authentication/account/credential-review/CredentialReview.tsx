import { useActions, useValues } from 'kea'

import * as heartPng from '@posthog/brand/hoggies/png/heart'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SceneExport } from 'scenes/sceneTypes'
import { connectedAppsLogic } from 'scenes/settings/user/connectedAppsLogic'
import { passkeySettingsLogic } from 'scenes/settings/user/passkeySettingsLogic'
import { personalAPIKeysLogic } from 'scenes/settings/user/personalAPIKeysLogic'

import { credentialReviewLogic } from './credentialReviewLogic'
import { CredentialsReviewList } from './CredentialsReviewList'

export const scene: SceneExport = {
    component: CredentialReview,
    logic: credentialReviewLogic,
}

const HedgehogHeart = pngHoggie(heartPng)

export function CredentialReview(): JSX.Element {
    const { markComplete } = useActions(credentialReviewLogic)
    const { keysLoading } = useValues(personalAPIKeysLogic)
    const { passkeysLoading } = useValues(passkeySettingsLogic)
    const { connectedAppsLoading } = useValues(connectedAppsLogic)

    const loading = keysLoading || passkeysLoading || connectedAppsLoading

    return (
        <BridgePage view="credential-review" fixedWidth={false}>
            <div className="px-12 py-8 flex flex-col items-center max-w-3xl w-full text-center">
                <h2 className="text-lg">Welcome to PostHog!</h2>
                <h1 className="text-3xl font-bold">One more thing.</h1>
                <div className="max-w-60 my-8">
                    <HedgehogHeart className="w-full h-full" />
                </div>
                <p className="mb-6 max-w-xl">
                    Your account was set up with the credentials and connected apps listed below. Review them and revoke
                    anything you don't recognize before continuing.
                </p>
                <div className="w-full mb-6 text-left">
                    <CredentialsReviewList />
                </div>
                <LemonButton
                    type="primary"
                    size="large"
                    onClick={() => markComplete()}
                    disabledReason={loading ? 'Loading your credentials…' : null}
                >
                    Continue to PostHog
                </LemonButton>
            </div>
        </BridgePage>
    )
}
