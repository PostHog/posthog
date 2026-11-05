import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'
import type { StoreChoice } from '@/posthog/credential-store/types'

import { ApiError } from './api'
import type { CredentialSource } from './credentials'

export type AuthStatus =
    | {
          authenticated: false
          next: string
          error?: string
          host?: string
          projectId?: string
          source?: CredentialSource
      }
    | {
          authenticated: true
          host: string
          projectId: string
          projectName: string | null
          kind: 'personal_api_key' | 'oauth'
          source: CredentialSource
          // Set when the source is the store.
          store: StoreChoice | null
          credentialsPath: string | null
          // What an OAuth login may do and when its access token expires (ISO 8601). Null for a
          // personal API key, which has no expiry and whose scopes PostHog doesn't report.
          scopes: string[] | null
          expiresAt: string | null
          // Null when the key lacks the user:read scope, so hog can't tell whose key it is.
          user: { email: string; name: string | null } | null
      }

export async function checkAuthStatus(ctx: Context): Promise<AuthStatus> {
    let credentials
    try {
        credentials = await ctx.credentials()
    } catch (error) {
        if (error instanceof HogError && error.code === 'not_authenticated') {
            return { authenticated: false, next: 'hog auth login' }
        }
        if (error instanceof HogError && error.code === 'session_expired') {
            return { authenticated: false, error: error.message, next: 'hog auth login' }
        }
        throw error
    }
    const { key, source } = credentials
    const { host, projectId } = key
    const { kind, scopes, expiresAt, rejected } = key.status()
    const api = await ctx.posthog()
    const [user, project] = await Promise.allSettled([
        api.get<{ email: string; first_name?: string }>('/api/users/@me/'),
        api.get<{ name: string }>(''),
    ])
    const failures = [user, project].flatMap((outcome) => (outcome.status === 'rejected' ? [outcome.reason] : []))
    if (failures.some((failure) => failure instanceof ApiError && failure.status === 401)) {
        return {
            authenticated: false,
            host,
            projectId,
            source,
            error: rejected,
            next: 'hog auth login',
        }
    }
    // A 403 means the key lacks the scope for that detail, not that it doesn't work.
    const fatal = failures.find((failure) => !(failure instanceof ApiError && failure.status === 403))
    if (fatal !== undefined) {
        throw fatal
    }
    return {
        authenticated: true,
        host,
        projectId,
        projectName: project.status === 'fulfilled' ? project.value.name : null,
        kind,
        source,
        store: credentials.source === 'store' ? credentials.store : null,
        credentialsPath: credentials.source === 'env' ? null : credentials.path,
        scopes,
        expiresAt: expiresAt === null ? null : new Date(expiresAt).toISOString(),
        user: user.status === 'fulfilled' ? { email: user.value.email, name: user.value.first_name || null } : null,
    }
}
