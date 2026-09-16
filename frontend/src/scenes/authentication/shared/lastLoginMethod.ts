import { useState } from 'react'

import { getCookie } from 'lib/api'

import { LoginMethod } from '~/types'

// pinned: posthog/middleware.py sets this cookie on a successful login, and the website reads it
export const LAST_LOGIN_METHOD_COOKIE = 'ph_last_login_method'

function readLastLoginMethod(): LoginMethod {
    return (getCookie(LAST_LOGIN_METHOD_COOKIE) as LoginMethod) ?? null
}

/** Read once per mount, because the cookie won't change while the page is open. */
export function useLastLoginMethod(): LoginMethod {
    const [lastLoginMethod] = useState(readLastLoginMethod)
    return lastLoginMethod
}
