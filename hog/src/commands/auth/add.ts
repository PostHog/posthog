import { printPending, refuseInCi, resumeApproval, runApproval, type PendingResult } from '@/core/approval'
import { defineCommand } from '@/core/command'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { ADD_COMMAND, loginFlow, loginWait, saveLogin } from '@/posthog/login/flow'
import type { OAuthLogin } from '@/posthog/oauth'

type AddResult =
    | (PendingResult & { host: string })
    | {
          status: 'added' | 'already_granted'
          host: string
          projectId: string
          // Set when the person picked another project on the approval page.
          previousProjectId: string | null
          // Every scope the login has now.
          scopes: string[]
          // False when PostHog didn't revoke the login this one replaced, which then works until it expires.
          replacedRevoked: boolean | null
      }

// Saves the approved login in place of the stored one.
async function finish(ctx: Context, approved: OAuthLogin): Promise<AddResult> {
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

export default defineCommand({
    description: 'Add scopes to your login, approved in the browser',
    writes: true,
    args: {
        scopes: { description: 'The scopes to add, such as insight:write', optional: true, variadic: true },
    },
    options: {
        wait: {
            type: 'boolean',
            description:
                'Wait for the scopes an agent or script asked for, and save the token once a person approves them',
        },
    },
    notes: [
        'hog asks for the scopes your login has plus the new ones. The approval page keeps the new ones ticked, and you can remove any of the others.',
        'Agents and scripts get a link and a code to hand to a person, then finish with `hog auth add --wait`.',
        'A personal API key keeps the scopes it has in PostHog. Add scopes to it under Settings, Personal API keys.',
    ].join('\n'),
    examples: ['hog auth add insight:write', 'hog auth add insight:write dashboard:write', 'hog auth add --wait'],

    async run({ args, options, ctx }): Promise<AddResult> {
        if (options.wait && args.scopes.length > 0) {
            throw new HogError(
                'scopes_with_wait',
                '--wait finishes the scopes you already asked for, so it takes no scopes.',
                'Run `hog auth add --wait` on its own, or `hog auth add <scope...>` to ask for other scopes.',
                EXIT_USAGE
            )
        }
        if (options.wait) {
            return finish(ctx, await resumeApproval(ctx, loginWait(ctx.runtime, ADD_COMMAND)))
        }
        if (args.scopes.length === 0) {
            throw new HogError(
                'scopes_required',
                'hog auth add needs the scopes to add.',
                'Name them, as in `hog auth add insight:write dashboard:write`.',
                EXIT_USAGE
            )
        }
        // The scope list is large, so only this command loads it.
        const { parseScope, scopesNotCovered } = await import('@/posthog/scopes')
        const wanted = args.scopes.map(parseScope)

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

        const flow = loginFlow(ctx.runtime, key.host, [...held, ...added], {
            command: ADD_COMMAND,
            requiredScopes: added,
        })
        const result = await runApproval(ctx, flow)
        return result.status === 'pending' ? { ...result, host: key.host } : finish(ctx, result.value)
    },

    human({ result, out }) {
        switch (result.status) {
            case 'pending':
                printPending(out, result)
                return
            case 'already_granted':
                out.line(`Your login for ${result.host} already has these scopes.`)
                return
            case 'added':
                out.line(`${out.style('Scopes added', 'green', 'bold')} to your login for ${result.host}.`)
                if (result.previousProjectId) {
                    out.line(
                        out.style(
                            `The login now works in project ${result.projectId} instead of ${result.previousProjectId}.`,
                            'yellow'
                        )
                    )
                }
                if (result.replacedRevoked === false) {
                    out.line(
                        out.style(
                            "PostHog didn't revoke the login this one replaced. It stops working when it expires, or remove it under Settings, Connected apps.",
                            'yellow'
                        )
                    )
                }
        }
    },

    telemetry: ({ result }) => ({ step_up_status: result.status }),
})
