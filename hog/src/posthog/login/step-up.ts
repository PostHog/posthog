import { refuseInCi, runApproval, type PendingResult } from '@/core/approval'
import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'
import type { OAuthLogin } from '@/posthog/oauth'
import { addToKeyHint, canStepUp } from '@/posthog/scope-challenge'
import { parseScope, scopesNotCovered } from '@/posthog/scopes'

import { ADD_COMMAND, loginFlow, saveLogin } from './flow'

export type StepUpResult =
    | (PendingResult & { host: string })
    | {
          status: 'added' | 'already_granted'
          host: string
          projectId: string
          // Set when the person picked another project on the approval page.
          previousProjectId: string | null
          scopes: string[]
          // False when PostHog didn't revoke the replaced login, which then works until it expires.
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

// At a terminal, asks to add the scopes, waits for the approval in the browser, and moves the session
// to the new login. Resolves to false when nobody can answer, the credentials can't add scopes, or the
// person says no, so the caller reports the missing scopes instead.
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

// `hog auth add`: a device login for the scopes the login holds plus the ones it lacks, with those
// marked required. At a terminal it waits for the approval and saves the login. Agents get the link.
export async function stepUp(ctx: Context, scopes: readonly string[]): Promise<StepUpResult> {
    const wanted = scopes.map(parseScope)
    const credentials = await ctx.credentials()
    const { key } = credentials
    const held = key.status().scopes
    if (!canStepUp(credentials) || held === null) {
        throw keyCantStepUp(wanted)
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
