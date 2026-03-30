import { Turnstile, type TurnstileInstance } from '@marsidev/react-turnstile'
import { useActions, useValues } from 'kea'
import { useCallback, useRef, useState } from 'react'

import { LemonButton, Link, Spinner } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'

import { signupLogic } from './signupLogic'

interface TurnstileChallengeProps {
    siteKey: string
}

export function TurnstileChallenge({ siteKey }: TurnstileChallengeProps): JSX.Element {
    const { setTurnstileToken } = useActions(signupLogic)
    const { turnstileToken, signupPanelEmail } = useValues(signupLogic)
    const { openSupportForm } = useActions(supportLogic)
    const turnstileRef = useRef<TurnstileInstance>(null)
    const [error, setError] = useState(false)
    const [failureCount, setFailureCount] = useState(0)

    const handleRetry = useCallback(() => {
        setError(false)
        turnstileRef.current?.reset()
    }, [])

    const handleError = useCallback(() => {
        setFailureCount((c) => c + 1)
        setError(true)
    }, [])

    if (turnstileToken) {
        return (
            <div className="flex items-center justify-center gap-2 py-2">
                <Spinner className="text-base" />
                <span className="text-sm text-secondary">Creating your account...</span>
            </div>
        )
    }

    return (
        <div className="flex flex-col items-center gap-2">
            <Turnstile
                ref={turnstileRef}
                siteKey={siteKey}
                onSuccess={setTurnstileToken}
                onError={handleError}
                onExpire={handleError}
                options={{ theme: 'auto' }}
            />
            {error && (
                <>
                    <LemonButton type="secondary" size="small" onClick={handleRetry}>
                        Try again
                    </LemonButton>
                    {failureCount >= 2 && (
                        <p className="text-sm text-secondary">
                            Having trouble signing up?{' '}
                            <Link
                                data-attr="turnstile-error-contact-support"
                                onClick={(e) => {
                                    e.preventDefault()
                                    openSupportForm({
                                        kind: 'support',
                                        target_area: 'login',
                                        email: signupPanelEmail.email,
                                    })
                                }}
                            >
                                Need help?
                            </Link>
                        </p>
                    )}
                </>
            )}
        </div>
    )
}
