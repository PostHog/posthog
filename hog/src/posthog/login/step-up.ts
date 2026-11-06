import { refuseInCi, runApproval, type PendingResult } from '@/core/approval'
import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'
import type { OAuthLogin } from '@/posthog/oauth'
import { scopesNotCovered } from '@/posthog/scopes'

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
        `Add ${scopes.join(', ')} to the key in PostHog under Settings, Personal API keys. Or run \`hog auth login\` to log in with the browser instead.`
    )
}

// `hog auth add`: a device login for the scopes the login holds plus the ones it lacks, with those
// marked required. At a terminal it waits for the approval and saves the login. Agents get the link.
export async function stepUp(ctx: Context, wanted: readonly string[]): Promise<StepUpResult> {
    const credentials = await ctx.credentials()
    const { key } = credentials
    const { kind, scopes: held } = key.status()
    if (credentials.source !== 'store' || kind !== 'oauth' || held === null) {
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
