import { Turnstile } from '@marsidev/react-turnstile'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { loginLogic } from '../loginLogic'

const SCRIPT_LOAD_TIMEOUT_MS = 10_000

export function LoginTurnstileWidget({ siteKey }: { siteKey: string }): JSX.Element {
    const { turnstileScriptFailed } = useValues(loginLogic)
    const { setTurnstileToken, setTurnstileClientStatus } = useActions(loginLogic)

    useEffect(() => {
        setTurnstileToken(null)
        setTurnstileClientStatus(turnstileScriptFailed ? 'script_failed' : 'pending')
        // A blocker extension often stops the script without an error event. `onLoadScript` fires when the
        // script tag is added, not when it runs, so only `window.turnstile` proves the script loaded.
        const timer = window.setTimeout(() => {
            if (typeof (window as any).turnstile === 'undefined') {
                setTurnstileClientStatus('script_failed')
            }
        }, SCRIPT_LOAD_TIMEOUT_MS)
        return () => {
            window.clearTimeout(timer)
            setTurnstileToken(null)
            setTurnstileClientStatus('not_rendered')
        }
        // Runs once per mount, so a status change does not restart the script timer
    }, []) // oxlint-disable-line react-hooks/exhaustive-deps

    const dropToken = (status: 'error' | 'expired' | 'unsupported'): void => {
        setTurnstileToken(null)
        setTurnstileClientStatus(status)
    }

    return (
        <Turnstile
            siteKey={siteKey}
            options={{ action: 'login', appearance: 'interaction-only', theme: 'auto' }}
            scriptOptions={{ onError: () => setTurnstileClientStatus('script_failed') }}
            onSuccess={(token) => {
                setTurnstileToken(token)
                setTurnstileClientStatus('token')
            }}
            onError={() => dropToken('error')}
            onTimeout={() => dropToken('error')}
            onExpire={() => dropToken('expired')}
            onUnsupported={() => dropToken('unsupported')}
        />
    )
}
