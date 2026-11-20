import { configPathFor, updateConfig, type PostHogConfig } from '@/core/config'
import type { Context } from '@/core/context'
import type { AccessKey } from '@/posthog/access-key'
import type { StoreChoice } from '@/posthog/credential-store/types'
import { sameHost, type Host } from '@/posthog/host'
import { parseProjectId, type ProjectId } from '@/posthog/ids'

import { saveLogin } from './flow'

export interface ConfigWrite {
    path: string
    status: 'created' | 'updated' | 'unchanged' | 'failed'
    error: string | null
}

export interface FinishedLogin {
    status: 'logged_in'
    host: string
    projectId: string
    store: StoreChoice
    credentialsPath: string | null
    keychainError: string | null
    // What the login may do, as PostHog reports it.
    scopes: string[] | null
    // ISO 8601, for an OAuth login. hog renews the token before then.
    expiresAt: string | null
    config: ConfigWrite
}

export function hasLogin(
    config: PostHogConfig | undefined,
    { host, projectId }: { host: Host; projectId: ProjectId }
): boolean {
    return (
        config?.host !== undefined &&
        sameHost(config.host, host) &&
        config.projectId !== undefined &&
        parseProjectId(config.projectId) === projectId
    )
}

// Commands pick their login from the closest posthog.json, so login writes its host and project
// there. A new file goes in this folder. The login is already saved, so a failed write only warns.
// The caller reloads `ctx` after a write.
export async function writeLoginToConfig(
    ctx: Context,
    login: { host: Host; projectId: ProjectId }
): Promise<ConfigWrite> {
    const loaded = await ctx.config()
    if (hasLogin(loaded?.config, login)) {
        return { path: configPathFor(ctx.runtime, loaded), status: 'unchanged', error: null }
    }

    try {
        const path = await updateConfig(ctx.runtime, loaded, (raw) => {
            raw.host = login.host
            raw.projectId = Number(login.projectId)
        })

        return { path, status: loaded ? 'updated' : 'created', error: null }
    } catch (error) {
        const path = configPathFor(ctx.runtime, loaded)
        return { path, status: 'failed', error: error instanceof Error ? error.message : String(error) }
    }
}

export async function finishLogin(ctx: Context, key: AccessKey): Promise<FinishedLogin> {
    const loggedIn = await saveLogin(ctx.runtime, key)
    const config = await writeLoginToConfig(ctx, loggedIn)
    ctx.reload()
    ctx.telemetry.loggedInAs(key)
    const { host, projectId, store, credentialsPath, keychainError, status } = loggedIn
    const { scopes, expiresAt } = status
    return {
        status: 'logged_in',
        host,
        projectId,
        store,
        credentialsPath,
        keychainError,
        scopes,
        expiresAt: expiresAt === null ? null : new Date(expiresAt).toISOString(),
        config,
    }
}
