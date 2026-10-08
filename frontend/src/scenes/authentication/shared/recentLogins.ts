import { SSO_PROVIDER_NAMES } from 'lib/constants'

import { LoginMethod, UserType } from '~/types'

import { readLastLoginMethod } from './lastLoginMethod'

export interface RecentLogin {
    email: string
    method: LoginMethod
    lastUsedAt: string
}

// pinned: a rename empties every saved list. Storage is per origin, so each region keeps its own list.
export const RECENT_LOGINS_STORAGE_KEY = 'ph_recent_logins'
export const MAX_RECENT_LOGINS = 3

const KNOWN_LOGIN_METHODS: string[] = ['password', 'passkey', ...Object.keys(SSO_PROVIDER_NAMES)]

function isRecentLogin(value: unknown): value is RecentLogin {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const { email, method, lastUsedAt } = value as Record<string, unknown>
    return (
        typeof email === 'string' &&
        email.length > 0 &&
        typeof lastUsedAt === 'string' &&
        (method === null || (typeof method === 'string' && KNOWN_LOGIN_METHODS.includes(method)))
    )
}

// Storage can be blocked, full, or edited by hand, so a failed read or write never breaks the login page
export function readRecentLogins(): RecentLogin[] {
    try {
        const stored: unknown = JSON.parse(window.localStorage.getItem(RECENT_LOGINS_STORAGE_KEY) ?? '[]')
        return Array.isArray(stored) ? stored.filter(isRecentLogin).slice(0, MAX_RECENT_LOGINS) : []
    } catch {
        return []
    }
}

function writeRecentLogins(recentLogins: RecentLogin[]): void {
    try {
        window.localStorage.setItem(RECENT_LOGINS_STORAGE_KEY, JSON.stringify(recentLogins))
    } catch {
        // A blocked or full storage only loses the list
    }
}

function isSameEmail(a: string, b: string): boolean {
    return a.toLowerCase() === b.toLowerCase()
}

// An impersonated session writes nothing, so a staff browser never collects the addresses it helps
export function recordRecentLogin(user: Pick<UserType, 'email' | 'is_impersonated'>, now: Date = new Date()): void {
    if (user.is_impersonated || !user.email) {
        return
    }
    const recentLogin: RecentLogin = {
        email: user.email,
        method: readLastLoginMethod(),
        lastUsedAt: now.toISOString(),
    }
    const others = readRecentLogins().filter(({ email }) => !isSameEmail(email, user.email))
    writeRecentLogins([recentLogin, ...others].slice(0, MAX_RECENT_LOGINS))
}
