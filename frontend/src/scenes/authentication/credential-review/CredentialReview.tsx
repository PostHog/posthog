import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { HeartHog } from 'lib/components/hedgehogs'
import { SceneExport } from 'scenes/sceneTypes'

import { credentialReviewLogic } from './credentialReviewLogic'
import { CredentialsReviewList } from './CredentialsReviewList'

export const scene: SceneExport = {
    component: CredentialReview,
    logic: credentialReviewLogic,
}

export function CredentialReview(): JSX.Element {
    const { markComplete } = useActions(credentialReviewLogic)

    return (
        <BridgePage view="credential-review" fixedWidth={false}>
            <div className="px-12 py-8 flex flex-col items-center max-w-3xl w-full text-center">
                <h2 className="text-lg">Welcome to PostHog!</h2>
                <h1 className="text-3xl font-bold">One more thing.</h1>
                <div className="max-w-60 my-8">
                    <HeartHog className="w-full h-full" />
                </div>
                <p className="mb-6 max-w-xl">
                    Your account was set up with the API keys listed below. Review what each one can access, and revoke
                    any you don't recognize before continuing.
                </p>
                <div className="w-full mb-6 text-left">
                    <CredentialsReviewList />
                </div>
                <LemonButton type="primary" size="large" onClick={() => markComplete()}>
                    Continue to PostHog
                </LemonButton>
            </div>
        </BridgePage>
    )
}
