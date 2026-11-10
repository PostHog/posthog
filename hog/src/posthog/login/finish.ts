import { join } from 'node:path'

import { CONFIG_FILE, updateConfig, type PostHogConfig } from '@/core/config'
import type { Context } from '@/core/context'
import type { AccessKey } from '@/posthog/access-key'
import type { StoreChoice } from '@/posthog/credential-store/types'
import type { Host } from '@/posthog/host'
import { parseProjectId, type ProjectId } from '@/posthog/ids'

import { saveLogin } from './flow'

export interface NamedIn {
    path: string
    status: 'created' | 'updated' | 'unchanged' | 'failed'
    // Why hog couldn't write the file. Null unless `status` is failed.
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
    config: NamedIn
}

export function configNames(
    config: PostHogConfig | undefined,
    { host, projectId }: { host: Host; projectId: ProjectId }
): boolean {
    return config?.host === host && config.projectId !== undefined && parseProjectId(config.projectId) === projectId
}

// Commands pick a login from the closest posthog.json, so the login names itself there. The file in
// this folder or above it keeps its other settings, and a new one goes in this folder.
// The login is already saved, so a file hog can't write only warns. The caller reloads `ctx` after a write.
export async function nameInConfig(ctx: Context, target: { host: Host; projectId: ProjectId }): Promise<NamedIn> {
    const loaded = await ctx.config()
    if (loaded && configNames(loaded.config, target)) {
        return { path: loaded.path, status: 'unchanged', error: null }
    }
    const { host, projectId } = target
    const path = loaded?.path ?? join(ctx.runtime.cwd(), CONFIG_FILE)
    try {
        await updateConfig(ctx.runtime, loaded, (raw) => {
            raw.host = host
            raw.projectId = Number(projectId)
        })
    } catch (error) {
        return { path, status: 'failed', error: error instanceof Error ? error.message : String(error) }
    }
    return { path, status: loaded ? 'updated' : 'created', error: null }
}

export async function finishLogin(ctx: Context, key: AccessKey): Promise<FinishedLogin> {
    const loggedIn = await saveLogin(ctx.runtime, key)
    const config = await nameInConfig(ctx, loggedIn)
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
