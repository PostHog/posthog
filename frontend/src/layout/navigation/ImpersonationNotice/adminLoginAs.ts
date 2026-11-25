import { getCookie } from 'lib/api'

import { usersRetrieve } from '~/generated/core/api'
import type { UserApi } from '~/generated/core/api.schemas'

import { ImpersonationSessionUncertainError } from './ImpersonationSessionUncertainError'

async function ensureAdminOAuth2(): Promise<void> {
    const authCheckResponse = await fetch('/admin/auth_check', {
        method: 'GET',
        credentials: 'same-origin',
        redirect: 'manual',
    })

    if (authCheckResponse.ok) {
        return
    }

    const width = 600
    const height = 700
    const left = window.screen.width / 2 - width / 2
    const top = window.screen.height / 2 - height / 2

    const authWindow = window.open(
        '/admin/oauth2/success',
        'admin_oauth2',
        `width=${width},height=${height},top=${top},left=${left},toolbar=no,location=no,directories=no,status=no,menubar=no,scrollbars=yes,resizable=yes`
    )

    if (!authWindow) {
        throw new Error('Popup blocked. Please allow popups for this site and try again.')
    }

    // Resolve ONLY once the popup confirms success via `oauth2_complete`. A popup that closes
    // without sending it means the admin session was never established — proceeding anyway would
    // fire the impersonation POST against a stale session, which silently fails and forces a retry.
    await new Promise<void>((resolve, reject) => {
        let checkClosed: ReturnType<typeof setInterval>
        let gracePeriodTimeout: ReturnType<typeof setTimeout> | null = null
        let completed = false

        const cleanup = (): void => {
            clearInterval(checkClosed)
            if (gracePeriodTimeout) {
                clearTimeout(gracePeriodTimeout)
            }
            window.removeEventListener('message', handleMessage)
        }

        const handleMessage = (event: MessageEvent): void => {
            if (event.origin !== window.location.origin) {
                return
            }
            if (event.data?.type === 'oauth2_complete') {
                completed = true
                cleanup()
                resolve()
            }
        }
        window.addEventListener('message', handleMessage)

        checkClosed = setInterval(() => {
            if (authWindow.closed) {
                clearInterval(checkClosed)
                // The success message can land a tick after the popup closes — give it a brief
                // grace period before deciding this was a cancellation.
                gracePeriodTimeout = setTimeout(() => {
                    if (!completed) {
                        cleanup()
                        reject(new Error('Admin authentication was cancelled. Please try impersonating again.'))
                    }
                }, 500)
            }
        }, 500)
    })
}

async function verifyImpersonatedSession(userId: number, readOnly: boolean): Promise<void> {
    let user: UserApi
    try {
        user = await usersRetrieve('@me')
        if (!user || !Number.isSafeInteger(user.id) || user.id <= 0 || typeof user.is_impersonated !== 'boolean') {
            throw new Error('Invalid session identity response')
        }
    } catch (error) {
        throw new ImpersonationSessionUncertainError('Could not verify the session. Reload the page to continue.', {
            cause: error,
        })
    }
    if (user.id !== userId || !user.is_impersonated) {
        const LoginError = user.is_impersonated ? ImpersonationSessionUncertainError : Error
        throw new LoginError('Could not log in as this user. Check that impersonation is allowed and try again.')
    }
    if (user.is_impersonated_read_only !== readOnly) {
        throw new ImpersonationSessionUncertainError('Could not verify the session. Reload the page to continue.')
    }
}

export interface AdminLoginAsParams {
    userId: number
    reason: string
    readOnly: boolean
}

export async function adminLoginAs({ userId, reason, readOnly }: AdminLoginAsParams): Promise<void> {
    await ensureAdminOAuth2()

    let loginResponse: Response
    try {
        loginResponse = await fetch(`/admin/login/user/${userId}/`, {
            method: 'POST',
            credentials: 'same-origin',
            mode: 'cors',
            headers: {
                Accept: 'application/json',
                'X-CSRFToken': getCookie('posthog_csrftoken') as string,
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: new URLSearchParams({
                read_only: readOnly ? 'true' : 'false',
                reason,
            }),
        })
        if (loginResponse.ok && (await loginResponse.json())?.success !== true) {
            throw new Error('The login response did not confirm success')
        }
    } catch (error) {
        throw new ImpersonationSessionUncertainError(
            'Could not confirm the login result. Reload the page to continue.',
            {
                cause: error,
            }
        )
    }

    if (!loginResponse.ok) {
        const LoginError =
            loginResponse.status >= 500 || loginResponse.redirected ? ImpersonationSessionUncertainError : Error
        throw new LoginError(`django-loginas request resulted in status ${loginResponse.status}`)
    }

    await verifyImpersonatedSession(userId, readOnly)
}
