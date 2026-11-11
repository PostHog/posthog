import { clearPending, refuseInCi, runApproval, waitIdentity, type PendingResult } from '@/core/approval'
import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'
import type { AccessKey } from '@/posthog/access-key'
import { stepUpRequired } from '@/posthog/api'
import type { LoginTarget } from '@/posthog/credential-store/item-name'
import { CI_CREDENTIALS_HINT } from '@/posthog/credentials'
import type { Credentials } from '@/posthog/credentials'
import { sameHost } from '@/posthog/host'
import type { OAuthLogin } from '@/posthog/oauth'
import { addToKeyHint, canStepUp, fewestScopes, isScopeName } from '@/posthog/scope-challenge'
import { scopesNotCovered } from '@/posthog/scopes'

import { ADD_COMMAND, loginFlow, saveLogin } from './flow'

export type StepUpResult =
    | (PendingResult & { host: string })
    | {
          status: 'added' | 'already_granted'
          host: string
          projectId: string
          scopes: string[]
          replacedRevoked: boolean | null
      }

export async function finishStepUp(ctx: Context, approved: OAuthLogin, expected: LoginTarget): Promise<StepUpResult> {
    // The approval asked for this login's scopes. Saving it as another project's login would replace
    // the scopes that login has, so hog revokes it instead.
    if (sameHost(expected.host, approved.host) && expected.projectId !== approved.projectId) {
        // PostHog has redeemed the device code, so a retry must start a new approval.
        await Promise.all([approved.logout(ctx.runtime), clearPending(ctx.runtime, ADD_COMMAND)])
        throw new HogError(
            'step_up_other_project',
            `PostHog approved the scopes for project ${approved.projectId}, and hog asked for them for project ${expected.projectId}, so hog didn't save them.`,
            `Run the same \`hog auth add\` command again, and pick project ${expected.projectId} on the approval page.`
        )
    }

    const saved = await saveLogin(ctx.runtime, approved, { replace: (stored) => approved.continuing(stored) })

    return {
        status: 'added',
        host: saved.host,
        projectId: saved.projectId,
        scopes: saved.status.scopes ?? [],
        replacedRevoked: saved.replacedRevoked,
    }
}

// hog adds scopes by asking for a new browser approval, which only works for `hog auth login`. A personal
// API key's scopes are set in PostHog, so hog can't change them.
function personalKeyCantGainScopes(scopes: readonly string[]): HogError {
    return new HogError(
        'step_up_unavailable',
        "You're using a personal API key, and hog can't add scopes to it. You choose a key's scopes in PostHog.",
        `${addToKeyHint(scopes)} Or run \`hog auth login\` to log in with the browser, and hog can then add scopes for you.`
    )
}

// Agents, scripts, CI and `-o json` have no prompts, so this returns false without asking or waiting,
// and the caller fails with `step_up_required`, which names the scopes and the `hog auth add` command.
// It also returns false for a personal API key, or when the person says no.
export async function promptStepUp(ctx: Context, scopes: readonly string[]): Promise<boolean> {
    const prompts = ctx.prompts
    if (!prompts || !canStepUp(await ctx.credentials())) {
        return false
    }
    // An earlier step-up in this command can have added them already.
    const missing = (await loginScopes(ctx, await ctx.credentials(), scopes))?.missing ?? []
    if (missing.length === 0) {
        return true
    }
    const question = `This needs ${missing.join(', ')}, which your login doesn't have. Add these scopes now?`
    if (!(await prompts.confirm(question, { initialValue: true })) || (await stepUp(ctx, missing)).status !== 'added') {
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
    return { key, held, missing: fewestScopes(scopesNotCovered(held, wanted)) }
}

// At a terminal this waits for the approval and saves the login. Agents get the link.
export async function stepUp(ctx: Context, wanted: readonly string[]): Promise<StepUpResult> {
    const login = await loginScopes(ctx, await ctx.credentials(), wanted)
    if (!login) {
        throw personalKeyCantGainScopes(wanted)
    }

    const { key, held, missing: added } = login
    if (added.length === 0) {
        return {
            status: 'already_granted',
            host: key.host,
            projectId: key.projectId,
            scopes: held,
            replacedRevoked: null,
        }
    }

    refuseInCi(ctx, ADD_COMMAND, `${CI_CREDENTIALS_HINT} Either way, ask for the scopes the job needs.`)
    const flow = loginFlow(ctx.runtime, key.host, [...held, ...added], {
        identity: waitIdentity(ADD_COMMAND),
        requiredScopes: added,
        projectId: key.projectId,
    })
    const result = await runApproval(ctx, flow)

    return result.status === 'pending'
        ? { ...result, host: key.host }
        : finishStepUp(ctx, result.value, { host: key.host, projectId: key.projectId })
}

// Only a login knows its scopes without asking PostHog, so a personal API key meets the 403 instead.
export async function ensureScopes(ctx: Context, scopes: readonly string[], action = 'for this'): Promise<void> {
    const credentials = await ctx.credentials().catch(() => undefined)
    let login = await loginScopes(ctx, credentials, scopes)
    if (!login?.missing.length || !login.missing.every(isScopeName)) {
        return
    }
    // The person can untick scopes the login already had, so the whole set is checked again after.
    if (await ctx.stepUp(login.missing)) {
        login = await loginScopes(ctx, credentials, scopes)
        if (!login?.missing.length) {
            return
        }
    }
    const { missing, key } = login
    throw stepUpRequired(missing, { host: key.host, message: `Your login needs ${missing.join(', ')} ${action}.` })
}
