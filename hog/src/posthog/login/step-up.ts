import { refuseInCi, runApproval, type PendingResult } from '@/core/approval'
import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'
import type { OAuthLogin } from '@/posthog/oauth'
import { addToKeyHint, canStepUp } from '@/posthog/scope-challenge'
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
    const missing = scopesNotCovered((await ctx.session()).current.status().scopes ?? [], scopes)
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

// At a terminal this waits for the approval and saves the login. Agents get the link.
export async function stepUp(ctx: Context, wanted: readonly string[]): Promise<StepUpResult> {
    const credentials = await ctx.credentials()
    // The session, not the credentials, holds the login an earlier step-up in this command saved.
    const key = (await ctx.session()).current
    const held = key.status().scopes
    if (!canStepUp(credentials) || held === null) {
        throw personalKeyCantGainScopes(wanted)
    }
    const added = scopesNotCovered(held, wanted)
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
