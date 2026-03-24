import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { LemonButton, Link, Spinner } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'

import { signupLogic } from './signupLogic'

const TURNSTILE_SCRIPT_URL = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'

function loadTurnstileScript(): Promise<void> {
    if (window.turnstile) {
        return Promise.resolve()
    }
    return new Promise((resolve, reject) => {
        const existing = document.querySelector(`script[src="${TURNSTILE_SCRIPT_URL}"]`)
        if (existing) {
            if (window.turnstile) {
                resolve()
                return
            }
            existing.addEventListener('load', () => resolve())
            existing.addEventListener('error', () => reject(new Error('Failed to load Turnstile')))
            return
        }
        const script = document.createElement('script')
        script.src = TURNSTILE_SCRIPT_URL
        script.async = true
        script.onload = () => resolve()
        script.onerror = () => reject(new Error('Failed to load Turnstile'))
        document.head.appendChild(script)
    })
}

interface TurnstileChallengeProps {
    siteKey: string
}

export function TurnstileChallenge({ siteKey }: TurnstileChallengeProps): JSX.Element {
    const { setTurnstileToken } = useActions(signupLogic)
    const { turnstileToken, signupPanelEmail } = useValues(signupLogic)
    const { openSupportForm } = useActions(supportLogic)
    const containerRef = useRef<HTMLDivElement>(null)
    const widgetIdRef = useRef<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [loading, setLoading] = useState(true)
    const [failureCount, setFailureCount] = useState(0)

    const onSuccess = useCallback(
        (token: string) => {
            setTurnstileToken(token)
        },
        [setTurnstileToken]
    )

    const handleRetry = useCallback(() => {
        setError(null)
        if (widgetIdRef.current && window.turnstile) {
            window.turnstile.reset(widgetIdRef.current)
        }
    }, [])

    useEffect(() => {
        let cancelled = false

        loadTurnstileScript()
            .then(() => {
                if (cancelled || !containerRef.current || !window.turnstile) {
                    return
                }
                setLoading(false)
                widgetIdRef.current = window.turnstile.render(containerRef.current, {
                    sitekey: siteKey,
                    callback: onSuccess,
                    'error-callback': () => {
                        setFailureCount((c) => c + 1)
                        setError('Verification failed.')
                    },
                    'expired-callback': () => {
                        setFailureCount((c) => c + 1)
                        setError('Verification expired.')
                    },
                    theme: 'auto',
                })
            })
            .catch(() => {
                if (!cancelled) {
                    setLoading(false)
                    setError('Could not load verification.')
                }
            })

        return () => {
            cancelled = true
            if (widgetIdRef.current && window.turnstile) {
                window.turnstile.remove(widgetIdRef.current)
                widgetIdRef.current = null
            }
        }
    }, [siteKey, onSuccess])

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
            {loading && <Spinner className="text-xl" />}
            <div ref={containerRef} />
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
