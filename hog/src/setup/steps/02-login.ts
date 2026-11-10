import {
    pendingResult,
    refuseInCi,
    resumeApproval,
    reusablePending,
    runApproval,
    type ApprovalFlow,
    type ApprovalResult,
    type PendingResult,
} from '@/core/approval'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import type { AccessKey } from '@/posthog/access-key'
import { CI_CREDENTIALS_HINT } from '@/posthog/credentials'
import { LOGIN_SCOPES, type PendingLogin } from '@/posthog/device-auth'
import type { ProjectId } from '@/posthog/ids'
import { finishLogin } from '@/posthog/login/finish'
import { loginFlow, saveLogin } from '@/posthog/login/flow'
import type { OAuthLogin } from '@/posthog/oauth'

import type { Stop } from '../result'
import { runNext, type SetupRun, type Step } from '../setup-run'
import { SETUP_NEXT } from '../state'

function waitingStop(pending: PendingResult, projectId: ProjectId | undefined): Stop {
    const { url, code, expiresAt, next, instructions } = pending
    const project = projectId === undefined ? '' : ` Tell them to pick project ${projectId} on that page.`

    return {
        code: 'setup_login_pending',
        next: { kind: 'wait', command: next, url, code, expiresAt, instructions: `${instructions}${project}` },
    }
}

// An agent's first call gets the link, and its next call waits for that link. A person at the
// terminal waits in `runApproval`.
async function approve(
    ctx: Context,
    flow: ApprovalFlow<PendingLogin, OAuthLogin>
): Promise<ApprovalResult<OAuthLogin>> {
    const waiting = !ctx.prompts && (await reusablePending(ctx.runtime, flow, 0)) !== undefined
    if (!waiting) {
        return runApproval(ctx, flow)
    }

    const { value } = await resumeApproval(ctx, flow)
    return { status: 'approved', value }
}

// posthog.json comes with the repository, so a login to another project must not rename its project.
async function checkProject(run: SetupRun, key: AccessKey, expected: ProjectId | undefined): Promise<void> {
    if (expected === undefined || expected === key.projectId) {
        return
    }

    // The login works for its own project, so it stays saved.
    await saveLogin(run.ctx.runtime, key)
    throw new HogError(
        'setup_project_mismatch',
        `You approved project ${key.projectId}, but this folder uses project ${expected}.`,
        `Run \`${SETUP_NEXT}\` and pick project ${expected} on the approval page. To set up project ${key.projectId} instead, first change \`"projectId"\` in \`posthog.json\` or \`HOG_PROJECT_ID\`.`,
        EXIT_USAGE
    )
}

export const login: Step = {
    isDone: async (run) => (await run.login()) !== undefined,

    summary: async (run) => {
        const { host, projectId } = await run.requireLogin()
        return `Logged in to ${host}, project ${projectId}`
    },

    async advance(run) {
        const { ctx } = run
        const { host, projectId } = await run.target()
        const identity = { command: SETUP_NEXT, resume: SETUP_NEXT, pendingName: run.scope.pendingName }
        const flow = loginFlow(ctx.runtime, host, LOGIN_SCOPES, { identity })

        if (!run.input.next) {
            const pending = await reusablePending(ctx.runtime, flow)
            return pending
                ? waitingStop(pendingResult(flow, pending), projectId)
                : runNext(
                      'setup_login_needed',
                      `Run \`${SETUP_NEXT}\` to log in to ${host}. Users without an account can sign up on the same page.`
                  )
        }

        refuseInCi(ctx, SETUP_NEXT, CI_CREDENTIALS_HINT)
        const approval = await approve(ctx, flow)
        if (approval.status === 'pending') {
            return waitingStop(approval, projectId)
        }

        await checkProject(run, approval.value, projectId)
        const { config } = await finishLogin(ctx, approval.value)
        if (config.status === 'failed') {
            // Commands here pick the login from posthog.json, so setup can't go on without it.
            throw new HogError(
                'setup_config_unwritable',
                `You're logged in, but hog couldn't write ${config.path}: ${config.error ?? 'unknown error'}`,
                `Make ${run.scope.folder} writable, or add \`"host": "${host}"\` and \`"projectId": ${approval.value.projectId}\` to \`posthog.json\`. Then run \`${SETUP_NEXT}\`.`
            )
        }

        await run.complete('login')
        return undefined
    },
}
