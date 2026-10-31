import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'

import { ApiError } from './api'
import { posthogFile, type CredentialSource } from './credentials'

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
          source: CredentialSource
          credentialsPath: string | null
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
        throw error
    }
    const { host, projectId, source } = credentials
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
            error: 'PostHog rejected the key. Someone may have deleted it.',
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
        source,
        credentialsPath: source === 'credentials-file' ? posthogFile(ctx.runtime, 'credentials.json') : null,
        user: user.status === 'fulfilled' ? { email: user.value.email, name: user.value.first_name || null } : null,
    }
}
