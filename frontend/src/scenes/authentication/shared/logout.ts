import { getCookie } from 'lib/api'

/**
 * Log the current user out and, optionally, send them on to `nextUrl` afterwards.
 *
 * Django's `/logout` clears the session and honors a `next` field, so a full-page form POST is
 * the way to end the session and land back on a target URL in one step. Used by the account
 * mismatch screens, where the person is signed in under the wrong account and needs to log out
 * and continue where they were.
 */
export function submitLogoutForm(nextUrl?: string | null): void {
    const form = document.createElement('form')
    form.method = 'POST'
    form.action = '/logout'
    form.style.display = 'none'

    const csrfInput = document.createElement('input')
    csrfInput.type = 'hidden'
    csrfInput.name = 'csrfmiddlewaretoken'
    csrfInput.value = getCookie('posthog_csrftoken') || ''
    form.appendChild(csrfInput)

    if (nextUrl) {
        const nextInput = document.createElement('input')
        nextInput.type = 'hidden'
        nextInput.name = 'next'
        nextInput.value = nextUrl
        form.appendChild(nextInput)
    }

    document.body.appendChild(form)
    form.submit()
}
