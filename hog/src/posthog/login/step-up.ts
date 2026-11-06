import { refuseInCi, runApproval, type PendingResult } from '@/core/approval'
import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'
import type { AccessKey } from '@/posthog/access-key'
import { stepUpRequired } from '@/posthog/api'
import type { Credentials } from '@/posthog/credentials'
import type { OAuthLogin } from '@/posthog/oauth'
import { addToKeyHint, canStepUp, isScopeName } from '@/posthog/scope-challenge'
import { scopesNotCovered } from '@/posthog/scopes'

import { ADD_COMMAND, loginFlow, saveLogin } from './flow'

export type StepUpResult =
    | (PendingResult & { host: string })
    | {
          status: 'added' | 'already_granted'
          host: string
          projectId: string
          previousProjectId: string | null
          scopes: string[]
          replacedRevoked: boolean | null
      }

export async function finishStepUp(ctx: Context, approved: OAuthLogin): Promise<StepUpResult> {
    const saved = await saveLogin(ctx.runtime, approved, { replace: (stored) => approved.continuing(stored) })
    return {
        status: 'added',
        host: saved.host,
        projectId: saved.projectId,
        previousProjectId: saved.previousProjectId,
        scopes: saved.status.scopes ?? [],
        replacedRevoked: saved.replacedRevoked,
    }
}

function keyCantStepUp(scopes: readonly string[]): HogError {
    return new HogError(
        'step_up_unavailable',
        'hog can only add scopes to a login. A personal API key keeps the scopes it has in PostHog.',
        `${addToKeyHint(scopes)} Or run \`hog auth login\` to log in with the browser instead.`
    )
}

// Resolves to false when nobody can answer, the credentials can't add scopes, or the person says no.
export async function promptStepUp(ctx: Context, scopes: readonly string[]): Promise<boolean> {
    const prompts = ctx.prompts
    if (!prompts || !canStepUp(await ctx.credentials())) {
        return false
    }
    const question = `This needs ${scopes.join(', ')}, which your login doesn't have. Add these scopes now?`
    if (!(await prompts.confirm(question, { initialValue: true })) || (await stepUp(ctx, scopes)).status !== 'added') {
        return false
    }
    await (await ctx.session()).reload()
    return true
}

async function loginScopes(
    ctx: Context,
    credentials: Credentials | undefined,
    wanted: readonly string[]
): Promise<{ key: AccessKey; held: string[]; missing: string[] } | undefined> {
    if (!canStepUp(credentials)) {
        return undefined
    }
    // The session, not the credentials, holds the login an earlier step-up in this command saved.
    const key = (await ctx.session()).current
    const held = key.status().scopes
    if (held === null) {
        return undefined
    }
    return { key, held, missing: scopesNotCovered(held, wanted) }
}

// At a terminal this waits for the approval and saves the login. Agents get the link.
export async function stepUp(ctx: Context, wanted: readonly string[]): Promise<StepUpResult> {
    const login = await loginScopes(ctx, await ctx.credentials(), wanted)
    if (!login) {
        throw keyCantStepUp(wanted)
    }
    const { key, held, missing: added } = login
    if (added.length === 0) {
        return {
            status: 'already_granted',
            host: key.host,
            projectId: key.projectId,
            previousProjectId: null,
            scopes: held,
            replacedRevoked: null,
        }
    }
    refuseInCi(
        ctx,
        ADD_COMMAND,
        'Set HOG_PERSONAL_API_KEY, HOG_PROJECT_ID and HOG_HOST to a key with the scopes instead.'
    )
    const flow = loginFlow(ctx.runtime, key.host, [...held, ...added], { command: ADD_COMMAND, requiredScopes: added })
    const result = await runApproval(ctx, flow)
    return result.status === 'pending' ? { ...result, host: key.host } : finishStepUp(ctx, result.value)
}

// Only a login knows its scopes without asking PostHog, so a personal API key meets the 403 instead.
export async function ensureScopes(ctx: Context, scopes: readonly string[], action = 'for this'): Promise<void> {
    const credentials = await ctx.credentials().catch(() => undefined)
    const missing = (await loginScopes(ctx, credentials, scopes))?.missing ?? []
    // A name hog can't put in a command leaves the check to PostHog's 403.
    if (missing.length === 0 || !missing.every(isScopeName)) {
        return
    }
    if (!(await ctx.stepUp(missing))) {
        throw stepUpRequired(missing, `Your login needs ${missing.join(', ')} ${action}.`)
    }
}
