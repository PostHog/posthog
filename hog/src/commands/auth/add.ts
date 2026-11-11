import { printPending, resumeApproval, waitIdentity } from '@/core/approval'
import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { ADD_COMMAND, loginWait } from '@/posthog/login/flow'
import type { StepUpResult } from '@/posthog/login/step-up'

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
        'hog asks for the scopes you already have plus the new ones. The approval page keeps the new ones ticked, and you can remove any of the others.',
        'Agents and scripts get a link and a code to hand to a person, then finish with `hog auth add --wait`.',
        "hog can't add scopes to a personal API key. Add them to the key in PostHog under Settings, Personal API keys.",
    ].join('\n'),
    examples: ['hog auth add insight:write', 'hog auth add insight:write dashboard:write', 'hog auth add --wait'],

    async run({ args, options, ctx }): Promise<StepUpResult> {
        if (options.wait && args.scopes.length > 0) {
            throw new HogError(
                'scopes_with_wait',
                '--wait finishes the scopes you already asked for, so it takes no scopes.',
                'Run `hog auth add --wait` on its own, or `hog auth add <scope...>` to ask for other scopes.',
                EXIT_USAGE
            )
        }
        // The scope list is large, so commands that never step up don't load it.
        const { finishStepUp, stepUp } = await import('@/posthog/login/step-up')

        if (options.wait) {
            const { pending, value } = await resumeApproval(ctx, loginWait(ctx.runtime, waitIdentity(ADD_COMMAND)))
            // A request an older hog started doesn't name its project, so the approved one counts.
            return finishStepUp(ctx, value, { host: pending.host, projectId: pending.projectId ?? value.projectId })
        }

        if (args.scopes.length === 0) {
            throw new HogError(
                'scopes_required',
                'hog auth add needs the scopes to add.',
                'Name them, as in `hog auth add insight:write dashboard:write`.',
                EXIT_USAGE
            )
        }

        const { parseScope } = await import('@/posthog/scopes')
        return stepUp(ctx, args.scopes.map(parseScope))
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
                out.line(
                    `${out.style('Scopes added', 'green', 'bold')} to your login for project ${result.projectId} on ${result.host}.`
                )
                if (result.replacedRevoked === false) {
                    out.line(
                        out.style(
                            "PostHog didn't revoke your previous login. It stops working when it expires, or you can remove it in PostHog under Settings, Connected applications.",
                            'yellow'
                        )
                    )
                }
        }
    },

    telemetry: ({ result }) => ({ step_up_status: result.status }),
})
