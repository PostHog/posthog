import { Turnstile, type TurnstileInstance } from '@marsidev/react-turnstile'
import { useActions } from 'kea'
import { useCallback, useRef, useState } from 'react'

import { LemonButton, Link, Spinner } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'

interface TurnstileChallengeProps {
    siteKey: string
    onSuccess: (token: string) => void
    // When set, a spinner with this label replaces the check, because the form submits again with the token
    pendingLabel?: string
    troublePrompt: string
    email?: string
}

export function TurnstileChallenge({
    siteKey,
    onSuccess,
    pendingLabel,
    troublePrompt,
    email,
}: TurnstileChallengeProps): JSX.Element {
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

    if (pendingLabel) {
        return (
            <div className="flex items-center justify-center gap-2 py-2">
                <Spinner className="text-base" />
                <span className="text-sm text-secondary">{pendingLabel}</span>
            </div>
        )
    }

    return (
        <div className="flex flex-col items-center gap-2">
            <Turnstile
                ref={turnstileRef}
                siteKey={siteKey}
                onSuccess={onSuccess}
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
                            {/* Text is span-wrapped so Chrome's in-page translation (which replaces bare text
                                nodes with <font> elements) can't break React sibling ops — react#11538 */}
                            <span>{troublePrompt}</span>{' '}
                            <Link
                                data-attr="turnstile-error-contact-support"
                                onClick={(e) => {
                                    e.preventDefault()
                                    openSupportForm({
                                        kind: 'support',
                                        email,
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
