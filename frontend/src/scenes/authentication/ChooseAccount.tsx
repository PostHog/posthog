import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { AuthShell } from './AuthShell'
import { AccountChoice, chooseAccountLogic } from './chooseAccountLogic'

export function ChooseAccount(): JSX.Element {
    const { choices, choicesLoading, selectedUserId } = useValues(chooseAccountLogic)
    const { selectAccount } = useActions(chooseAccountLogic)
    const { preflight } = useValues(preflightLogic)

    return (
        <AuthShell
            view="login"
            showHedgehog
            message={
                <>
                    Welcome to
                    <br /> PostHog{preflight?.cloud ? ' Cloud' : ''}!
                </>
            }
        >
            <div className="space-y-4">
                <h2>Choose an account</h2>
                <p className="text-muted">
                    Your social account is linked to multiple PostHog accounts. Select which one you'd like to log in
                    to.
                </p>

                {choicesLoading ? (
                    <div className="space-y-2">
                        <LemonSkeleton className="h-12" />
                        <LemonSkeleton className="h-12" />
                    </div>
                ) : choices.length === 0 ? (
                    <LemonBanner type="error">
                        No account choices found. Your session may have expired. Please try logging in again.
                    </LemonBanner>
                ) : (
                    <div className="space-y-2">
                        {choices.map((choice: AccountChoice) => (
                            <LemonButton
                                key={choice.user_id}
                                type="secondary"
                                fullWidth
                                center
                                size="large"
                                loading={selectedUserId === choice.user_id}
                                disabled={selectedUserId !== null && selectedUserId !== choice.user_id}
                                onClick={() => selectAccount(choice.user_id)}
                                data-attr={`choose-account-${choice.user_id}`}
                            >
                                <div className="flex flex-col items-start py-1">
                                    {choice.name && <span className="font-semibold">{choice.name}</span>}
                                    <span className="text-muted text-sm">{choice.email}</span>
                                </div>
                            </LemonButton>
                        ))}
                    </div>
                )}
            </div>
        </AuthShell>
    )
}

export const scene: SceneExport = {
    component: ChooseAccount,
    logic: chooseAccountLogic,
}
