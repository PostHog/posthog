import posthog from 'posthog-js'

import { getCookie } from 'lib/api'

import { usersRetrieve } from '~/generated/core/api'

type ImpersonationFailureCause =
    | 'popup_blocked'
    | 'admin_auth_cancelled'
    | 'loginas_request_failed'
    | 'rejected'
    | 'unknown'

class AdminLoginAsError extends Error {
    readonly failureCause: ImpersonationFailureCause

    constructor(failureCause: ImpersonationFailureCause, message: string) {
        super(message)
        this.name = 'AdminLoginAsError'
        this.failureCause = failureCause
    }
}

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
        throw new AdminLoginAsError('popup_blocked', 'Popup blocked. Please allow popups for this site and try again.')
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
                        reject(
                            new AdminLoginAsError(
                                'admin_auth_cancelled',
                                'Admin authentication was cancelled. Please try impersonating again.'
                            )
                        )
                    }
                }, 500)
            }
        }, 500)
    })
}

export interface AdminLoginAsParams {
    userId: number
    reason: string
    readOnly: boolean
}

async function startImpersonation({ userId, reason, readOnly }: AdminLoginAsParams): Promise<void> {
    await ensureAdminOAuth2()

    const loginResponse = await fetch(`/admin/login/user/${userId}/`, {
        method: 'POST',
        credentials: 'same-origin',
        mode: 'cors',
        headers: {
            'X-CSRFToken': getCookie('posthog_csrftoken') as string,
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: new URLSearchParams({
            read_only: readOnly ? 'true' : 'false',
            reason,
        }),
    })

    if (!loginResponse.ok) {
        throw new AdminLoginAsError(
            'loginas_request_failed',
            `Impersonation request failed with status ${loginResponse.status}. Try again, and report it if it keeps happening.`
        )
    }

    // django-loginas answers a rejected attempt with a redirect back to the referer, so the
    // followed request lands on a 200 that is indistinguishable from a success. Ask the API who
    // we are now instead of trusting the status.
    const me = await usersRetrieve('@me')
    if (!me.is_impersonated) {
        throw new AdminLoginAsError(
            'rejected',
            'PostHog refused the impersonation. The user may be a staff member, or may have opted out of impersonation.'
        )
    }
}

export async function adminLoginAs(params: AdminLoginAsParams): Promise<void> {
    try {
        await startImpersonation(params)
    } catch (error) {
        posthog.capture('impersonation_failed', {
            cause: error instanceof AdminLoginAsError ? error.failureCause : 'unknown',
            target_user_id: params.userId,
            read_only: params.readOnly,
        })
        throw error
    }
}
