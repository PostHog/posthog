import { LoginMethod } from '~/types'

import { LAST_LOGIN_METHOD_COOKIE } from './lastLoginMethod'

export function setLastLoginMethodCookie(method: LoginMethod): void {
    if (method === null) {
        document.cookie = `${LAST_LOGIN_METHOD_COOKIE}=; max-age=0; path=/`
        return
    }
    document.cookie = `${LAST_LOGIN_METHOD_COOKIE}=${method}; path=/`
}
