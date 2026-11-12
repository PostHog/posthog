import { Turnstile } from '@marsidev/react-turnstile'
import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { loginLogic } from '../loginLogic'

const SCRIPT_LOAD_TIMEOUT_MS = 10_000

export function LoginTurnstileWidget({ siteKey }: { siteKey: string }): JSX.Element {
    const { setTurnstileToken, setTurnstileClientStatus } = useActions(loginLogic)
    const scriptLoaded = useRef(false)

    useEffect(() => {
        setTurnstileToken(null)
        setTurnstileClientStatus('pending')
        // A blocker extension often stops the script without an error event, so a script that never loads is a failure
        const timer = window.setTimeout(() => {
            if (!scriptLoaded.current) {
                setTurnstileClientStatus('script_failed')
            }
        }, SCRIPT_LOAD_TIMEOUT_MS)
        return () => {
            window.clearTimeout(timer)
            setTurnstileToken(null)
            setTurnstileClientStatus('not_rendered')
        }
    }, [setTurnstileToken, setTurnstileClientStatus])

    const dropToken = (status: 'error' | 'expired' | 'unsupported'): void => {
        setTurnstileToken(null)
        setTurnstileClientStatus(status)
    }

    return (
        <Turnstile
            siteKey={siteKey}
            options={{ action: 'login', appearance: 'interaction-only', theme: 'auto' }}
            onLoadScript={() => {
                scriptLoaded.current = true
            }}
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
