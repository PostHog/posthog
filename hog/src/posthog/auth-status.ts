import { z } from 'zod'

import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'
import type { StoreChoice } from '@/posthog/credential-store/types'

import type { AccessKeyStatus } from './access-key'
import { ApiError } from './api'
import type { CredentialSource } from './credentials'
import { ProjectMismatch, type LoginChoice } from './login/choose'

export type AuthStatus = (
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
          kind: AccessKeyStatus['kind']
          source: CredentialSource
          // Set when the source is the store.
          store: StoreChoice | null
          credentialsPath: string | null
          provider: string | null
          // What an OAuth login may do and when its access token expires (ISO 8601). Null for a
          // personal API key, which has no expiry and whose scopes PostHog doesn't report.
          scopes: string[] | null
          expiresAt: string | null
          // Null when the key lacks the user:read scope, so hog can't tell whose key it is.
          user: { email: string; name: string | null } | null
      }
) & {
    config: string | null
    // Which stored login hog picked and why. Null for credentials from the environment, --dotenv-file
    // or a CI job, and when hog found no login.
    login: LoginChoice | null
}

export async function checkAuthStatus(ctx: Context): Promise<AuthStatus> {
    const config = (await ctx.config())?.path ?? null
    let credentials

    try {
        credentials = await ctx.credentials()
    } catch (error) {
        if (error instanceof HogError && error.code === 'not_authenticated') {
            return { authenticated: false, next: 'hog auth login', config, login: null }
        }
        if (error instanceof HogError && error.code === 'session_expired') {
            return { authenticated: false, error: error.message, next: 'hog auth login', config, login: null }
        }
        if (error instanceof ProjectMismatch) {
            const { host, projectId } = error.target
            const next = error.command
            return { authenticated: false, error: error.message, next, host, projectId, config, login: null }
        }
        throw error
    }

    const { key, source } = credentials
    const login = credentials.source === 'store' ? credentials.choice : null
    const { host, projectId } = key
    const { kind, scopes, expiresAt, rejected, fix, provider } = key.status()

    const api = (await ctx.posthog()).withoutStepUp()
    const UserSchema = z.looseObject({ email: z.string(), first_name: z.string().nullish() })
    const [user, project] = await Promise.allSettled([
        key.identifiesPerson ? api.get('/api/users/@me/', UserSchema) : Promise.resolve(null),
        api.get('', z.looseObject({ name: z.string().nullish() })),
    ])

    const failures = [user, project].flatMap((outcome) => (outcome.status === 'rejected' ? [outcome.reason] : []))
    if (failures.some((failure) => failure instanceof ApiError && failure.status === 401)) {
        return {
            authenticated: false,
            host,
            projectId,
            source,
            error: rejected,
            next: fix,
            config,
            login,
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
        projectName: project.status === 'fulfilled' ? (project.value.name ?? null) : null,
        kind,
        source,
        store: credentials.source === 'store' ? credentials.store : null,
        credentialsPath:
            credentials.source === 'store' || credentials.source === 'dotenv-file' ? credentials.path : null,
        provider,
        scopes,
        expiresAt: expiresAt === null ? null : new Date(expiresAt).toISOString(),
        user:
            user.status === 'fulfilled' && user.value
                ? { email: user.value.email, name: user.value.first_name || null }
                : null,
        config,
        login,
    }
}
