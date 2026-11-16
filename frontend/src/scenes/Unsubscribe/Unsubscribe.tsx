import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { SceneExport } from 'scenes/sceneTypes'

import { unsubscribeLogic } from './unsubscribeLogic'

export const scene: SceneExport = {
    component: Unsubscribe,
    logic: unsubscribeLogic,
}

export function Unsubscribe(): JSX.Element {
    const { unsubscriptionLoading, unsubscription } = useValues(unsubscribeLogic)
    const { attemptUnsubscribe } = useActions(unsubscribeLogic)
    const notes = unsubscriptionLoading
        ? AUTH_NOTES.unsubscribe.loading
        : unsubscription === null
          ? AUTH_NOTES.unsubscribe.confirm
          : unsubscription
            ? AUTH_NOTES.unsubscribe.done
            : AUTH_NOTES.unsubscribe.failed

    return (
        <AuthScene notes={notes}>
            <AuthSceneCard>
                {unsubscription === null ? (
                    <>
                        <AuthCardTitle
                            title="Unsubscribe from this report?"
                            sub="You will stop receiving this subscription by email."
                        />
                        <LemonButton
                            type="primary"
                            data-attr="unsubscribe-confirm"
                            fullWidth
                            center
                            size="large"
                            onClick={attemptUnsubscribe}
                            loading={unsubscriptionLoading}
                        >
                            Unsubscribe
                        </LemonButton>
                    </>
                ) : unsubscription ? (
                    <AuthCardTitle
                        className="mb-0"
                        title="You have been unsubscribed!"
                        sub="You will no longer receive these kinds of emails."
                    />
                ) : (
                    <AuthCardTitle
                        className="mb-0"
                        title="Something went wrong!"
                        sub="You may already be unsubscribed or the link you clicked may be invalid."
                    />
                )}
            </AuthSceneCard>
        </AuthScene>
    )
}

export default Unsubscribe
