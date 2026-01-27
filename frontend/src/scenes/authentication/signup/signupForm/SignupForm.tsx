import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

import { userLogic } from '../../../userLogic'
import { SignupPanel1 } from './panels/SignupPanel1'
import { SignupPanel2 } from './panels/SignupPanel2'
import { SignupPanelAuth } from './panels/SignupPanelAuth'
import { SignupPanelEmail } from './panels/SignupPanelEmail'
import { SignupPanelOnboarding } from './panels/SignupPanelOnboarding'
import { signupLogic } from './signupLogic'

export const scene: SceneExport = {
    component: SignupForm,
    logic: signupLogic,
}

export function SignupForm(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const {
        isSignupPanelOnboardingSubmitting,
        signupPanelOnboardingManualErrors,
        isSignupPanel2Submitting,
        signupPanel2ManualErrors,
        panel,
        passkeySignupEnabled,
        panelTitle,
    } = useValues(signupLogic)
    const { setPanel } = useActions(signupLogic)
    const [showSpinner, setShowSpinner] = useState(true)

    useEffect(() => {
        setShowSpinner(true)
        const t = setTimeout(() => {
            setShowSpinner(false)
        }, 500)
        return () => clearTimeout(t)
    }, [panel])

    // Use new 3-panel flow when passkey signup is enabled
    if (passkeySignupEnabled) {
        return !user ? (
            <div className="deprecated-space-y-2">
                <h2>{panelTitle}</h2>
                {!isSignupPanelOnboardingSubmitting && signupPanelOnboardingManualErrors?.generic && (
                    <LemonBanner type="error">
                        {signupPanelOnboardingManualErrors.generic?.detail ||
                            'Could not complete your signup. Please try again.'}
                    </LemonBanner>
                )}
                {panel === 0 ? (
                    <SignupPanelEmail />
                ) : panel === 1 ? (
                    <>
                        <SignupPanelAuth />
                        <div className="flex justify-center">
                            <LemonButton
                                icon={<IconArrowLeft />}
                                onClick={() => setPanel(0)}
                                size="small"
                                center
                                data-attr="signup-go-back"
                            >
                                or go back
                            </LemonButton>
                        </div>
                    </>
                ) : (
                    <>
                        <SignupPanelOnboarding />
                        <div className="flex justify-center">
                            <LemonButton
                                icon={<IconArrowLeft />}
                                onClick={() => setPanel(panel - 1)}
                                size="small"
                                center
                                data-attr="signup-go-back"
                            >
                                or go back
                            </LemonButton>
                        </div>
                    </>
                )}
                {showSpinner ? <SpinnerOverlay sceneLevel /> : null}
            </div>
        ) : null
    }

    // Legacy 2-panel flow (when passkey signup is disabled)
    return !user ? (
        <div className="deprecated-space-y-2">
            <h2>{panelTitle}</h2>
            {!isSignupPanel2Submitting && signupPanel2ManualErrors?.generic && (
                <LemonBanner type="error">
                    {signupPanel2ManualErrors.generic?.detail || 'Could not complete your signup. Please try again.'}
                </LemonBanner>
            )}
            {panel === 0 ? (
                <SignupPanel1 />
            ) : (
                <>
                    <SignupPanel2 />
                    <div className="flex justify-center">
                        <LemonButton
                            icon={<IconArrowLeft />}
                            onClick={() => setPanel(panel - 1)}
                            size="small"
                            center
                            data-attr="signup-go-back"
                        >
                            or go back
                        </LemonButton>
                    </div>
                </>
            )}
            {showSpinner ? <SpinnerOverlay sceneLevel /> : null}
        </div>
    ) : null
}
