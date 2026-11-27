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
import { EXIT_NEEDS_PERSON, EXIT_USAGE, HogError } from '@/core/errors'
import type { AccessKey } from '@/posthog/access-key'
import { CI_CREDENTIALS_HINT } from '@/posthog/credentials'
import { LOGIN_SCOPES, type PendingLogin } from '@/posthog/device-auth'
import { REGION_CHOICES, REGIONS, regionOf, sameHost, type Host } from '@/posthog/host'
import type { ProjectId } from '@/posthog/ids'
import { finishLogin } from '@/posthog/login/finish'
import { loginFlow, saveLogin } from '@/posthog/login/flow'
import type { OAuthLogin } from '@/posthog/oauth'

import type { Stop } from '../result'
import { runNext, type SetupRun, type Step } from '../setup-run'
import { SETUP_COMMAND, updateState, type SetupState } from '../state'

function regionNote(host: Host, picked: SetupState['hostPicked'], named: boolean): string {
    const current = REGION_CHOICES.find((choice) => choice.value === regionOf(host))
    const other = REGION_CHOICES.find((choice) => choice.value !== current?.value)
    if (named || picked === undefined || !current || !other) {
        return ''
    }

    const where = picked === 'default' ? '' : ', where you last logged in'
    return `This uses PostHog ${current.label} (${current.hint})${where}. If your account is on ${other.hint}, or your data has to stay in ${other.value === 'eu' ? 'the EU' : 'the US'}, don't open the link. Tell me instead, and I'll switch to ${other.label}.`
}

function userMessage(url: string, code: string | null, project: string, region: string): string {
    return [
        `To connect this app to PostHog, open this link${code ? ` and approve the code ${code}` : ''}:`,
        url,
        "If you don't have a PostHog account yet, you can sign up on that page first.",
        project,
        region,
        "I'll carry on as soon as you approve it.",
    ]
        .filter(Boolean)
        .join('\n')
}

// An agent's tool call times out after a few minutes, so one `hog setup` waits this long at most and
// returns the same link for the agent to wait on again.
const AGENT_WAIT_MS = 90_000

// How long an agent keeps calling `hog setup` for one link before it hands the turn back to the person.
const KEEP_WAITING_MINUTES = 10

function waitingStop(pending: PendingResult, projectId: ProjectId | undefined, region: string): Stop {
    const { url, code, expiresAt, next } = pending
    const project = projectId === undefined ? '' : `Pick project ${projectId} on that page.`
    const switchTo = region
        ? ` If they ask for the other region, run \`${SETUP_COMMAND} --region <us|eu>\` and send the new message.`
        : ''

    return {
        code: 'setup_login_pending',
        next: {
            kind: 'wait',
            command: next,
            url,
            code,
            expiresAt,
            message: userMessage(url, code, project, region),
            instructions: `Send the user \`next.message\` as it is, with the full link, in a message they see now. Then run \`${SETUP_COMMAND}\` without waiting for a reply: it waits for the approval. While it returns this same link, run it again, for up to ${KEEP_WAITING_MINUTES} minutes. If they still haven't approved by then, end your turn and ask them to tell you once they have.${switchTo}`,
        },
    }
}

async function switchRegion(run: SetupRun, named: boolean): Promise<void> {
    const { region } = run.input
    const current = run.state?.host
    if (region === undefined || named || current === undefined || sameHost(REGIONS[region], current)) {
        return
    }

    run.state = await updateState(
        run.ctx,
        run.scope,
        (state) => state && { ...state, host: REGIONS[region], hostPicked: undefined }
    )
}

const REJECTED_HINT = `Don't install PostHog without the login, and don't write a placeholder token. Tell the user the login was rejected in the browser, so PostHog isn't set up, and that \`${SETUP_COMMAND}\` gives them a new link when they want to try again. Then end your turn.`

// An agent's first call gets the link, and its next call waits for that link. A person at the
// terminal waits in `runApproval`.
async function approve(
    ctx: Context,
    flow: ApprovalFlow<PendingLogin, OAuthLogin>
): Promise<ApprovalResult<OAuthLogin>> {
    const pending = ctx.prompts ? undefined : await reusablePending(ctx.runtime, flow, 0)
    if (!pending) {
        return runApproval(ctx, flow)
    }

    try {
        const { value } = await resumeApproval(ctx, { ...flow, maxWaitMs: AGENT_WAIT_MS })
        return { status: 'approved', value }
    } catch (error) {
        if (error instanceof HogError && error.code === 'login_still_pending') {
            return pendingResult(flow, pending)
        }
        if (error instanceof HogError && error.code === 'login_rejected') {
            throw new HogError(
                'setup_login_rejected',
                'The login was rejected in the browser.',
                REJECTED_HINT,
                EXIT_NEEDS_PERSON
            )
        }
        throw error
    }
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
        `Run \`${SETUP_COMMAND}\` and pick project ${expected} on the approval page. To set up project ${key.projectId} instead, first change \`"projectId"\` in \`posthog.json\` or \`HOG_PROJECT_ID\`.`,
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
        const named = (await run.namedHost()) !== undefined
        await switchRegion(run, named)
        const { host, projectId } = await run.target()
        const region = regionNote(host, run.state?.hostPicked, named)
        const identity = { command: SETUP_COMMAND, resume: SETUP_COMMAND, pendingName: run.scope.pendingName }
        const flow = loginFlow(ctx.runtime, host, LOGIN_SCOPES, { identity })

        if (!run.input.next) {
            const pending = await reusablePending(ctx.runtime, flow)
            return pending
                ? waitingStop(pendingResult(flow, pending), projectId, region)
                : runNext(
                      'setup_login_needed',
                      `Run \`${SETUP_COMMAND}\` to get a login link for ${host}, then send the user the message it returns.`
                  )
        }

        refuseInCi(ctx, SETUP_COMMAND, CI_CREDENTIALS_HINT)
        const approval = await approve(ctx, flow)
        if (approval.status === 'pending') {
            return waitingStop(approval, projectId, region)
        }

        await checkProject(run, approval.value, projectId)
        const { config } = await finishLogin(ctx, approval.value)
        if (config.status === 'failed') {
            // Commands here pick the login from posthog.json, so setup can't go on without it.
            throw new HogError(
                'setup_config_unwritable',
                `You're logged in, but hog couldn't write ${config.path}: ${config.error ?? 'unknown error'}`,
                `Make ${run.scope.folder} writable, or add \`"host": "${host}"\` and \`"projectId": ${approval.value.projectId}\` to \`posthog.json\`. Then run \`${SETUP_COMMAND}\`.`
            )
        }

        await run.complete('login')
        return undefined
    },
}
