import { z } from 'zod'

import type { Context } from './context'
import { HogError } from './errors'
import { parseJsonOrUndefined } from './json'
import { escapeControls, type Output } from './output'
import { hogFile } from './paths'
import type { Spinner } from './prompts'
import type { Runtime } from './runtime'

// Something a person approves in a browser, saved in hog's folder while hog waits for them.
export const PendingApprovalSchema = z.object({
    url: z.string(),
    // The code the approval page shows, so the person can check it is the request they started.
    userCode: z.string().optional(),
    // Epoch milliseconds after which PostHog forgets the request.
    expiresAt: z.number(),
    intervalSeconds: z.number(),
})

export type PendingApproval = z.output<typeof PendingApprovalSchema>

export type PollOutcome<Value> =
    | { state: 'pending' }
    // RFC 8628 `slow_down`: poll less often from now on.
    | { state: 'slow_down' }
    // A failure that can pass, such as a 429 or a 5xx.
    | { state: 'retry'; reason: string }
    | { state: 'approved'; value: Value }
    | { state: 'rejected' }
    | { state: 'expired' }

// One command that waits for a person. Every such command goes through `runApproval`, so they all
// start, wait, resume and give up the same way.
export interface ApprovalFlow<Pending extends PendingApproval, Value> {
    // The command that starts it, like `hog auth login`. `<command> --wait` resumes it.
    command: string
    // What the person approves, in copy and in error codes, like `login`.
    noun: string
    // Reads the pending item back from its file. An item hog can't read counts as none.
    pending: z.ZodType<Pending>
    start: () => Promise<Pending>
    // Whether a pending item from an earlier run can stand in for a new one, so an agent that
    // retries hands the person the link it already shared.
    reuse?: (existing: Pending) => boolean
    // `timeoutMs` is how long the poll request may take before the request expires.
    poll: (pending: Pending, timeoutMs: number) => Promise<PollOutcome<Value>>
}

// What resuming a pending item needs. It can't start a new one.
export type ApprovalWait<Pending extends PendingApproval, Value> = Pick<
    ApprovalFlow<Pending, Value>,
    'command' | 'noun' | 'pending' | 'poll'
>

export type ApprovalResult<Value> =
    | {
          status: 'pending'
          url: string
          code: string | null
          expiresAt: string
          instructions: string
          next: string
      }
    | { status: 'approved'; value: Value }

const MAX_RETRIES = 3
const REQUEST_TIMEOUT_MS = 30_000
// RFC 8628 asks clients to poll this much slower after each `slow_down`.
const SLOW_DOWN_SECONDS = 5
// Reusing a request this close to expiry would hand the person a link that dies while they open it.
// Approving takes a few seconds, so the margin stays short.
const REUSE_MARGIN_MS = 20_000

function pendingPath(runtime: Runtime, command: string): string {
    return hogFile(runtime, `pending-${command.replace(/^hog /, '').replaceAll(' ', '-')}.json`)
}

async function readPending<Pending extends PendingApproval>(
    runtime: Runtime,
    flow: ApprovalWait<Pending, unknown>
): Promise<Pending | undefined> {
    try {
        return parseJsonOrUndefined(await runtime.readFile(pendingPath(runtime, flow.command)), flow.pending)
    } catch {
        return undefined
    }
}

export async function clearPending(runtime: Runtime, command: string): Promise<void> {
    await runtime.removeFile(pendingPath(runtime, command))
}

// A new start replaces the command's pending item, unless the flow can reuse it.
async function startPending<Pending extends PendingApproval, Value>(
    runtime: Runtime,
    flow: ApprovalFlow<Pending, Value>
): Promise<Pending> {
    const existing = await readPending(runtime, flow)
    if (existing && existing.expiresAt - runtime.now() > REUSE_MARGIN_MS && flow.reuse?.(existing)) {
        return existing
    }
    const pending = await flow.start()
    // The pending item can hold a secret, like a device code, so only its owner may read it.
    await runtime.writePrivateFile(pendingPath(runtime, flow.command), JSON.stringify(pending))
    return pending
}

// Polls until the person approves, rejects or lets the request expire, and forgets the pending item
// in each case. When hog loses contact with PostHog the item stays, so `--wait` can resume it.
async function waitFor<Pending extends PendingApproval, Value>(
    runtime: Runtime,
    flow: ApprovalWait<Pending, Value>,
    pending: Pending
): Promise<Value> {
    const interrupted = (reason: string): HogError =>
        new HogError(
            `${flow.noun}_interrupted`,
            `hog lost contact with PostHog while waiting for the ${flow.noun}: ${reason}`,
            `Run \`${flow.command} --wait\` to keep waiting. The link stays the same.`
        )
    const fail = async (error: HogError): Promise<never> => {
        await clearPending(runtime, flow.command)
        throw error
    }

    let failures = 0
    let intervalSeconds = pending.intervalSeconds
    while (runtime.now() < pending.expiresAt) {
        await runtime.sleep(intervalSeconds * 1000)
        const remaining = pending.expiresAt - runtime.now()
        if (remaining <= 0) {
            break
        }
        let outcome: PollOutcome<Value>
        try {
            outcome = await flow.poll(pending, Math.min(REQUEST_TIMEOUT_MS, remaining))
        } catch (error) {
            if (!(error instanceof HogError)) {
                throw error
            }
            if (error.code !== 'network_error') {
                return fail(error)
            }
            outcome = { state: 'retry', reason: error.message }
        }
        switch (outcome.state) {
            case 'retry':
                if (++failures > MAX_RETRIES) {
                    throw interrupted(outcome.reason)
                }
                continue
            case 'slow_down':
                intervalSeconds += SLOW_DOWN_SECONDS
                continue
            case 'pending':
                failures = 0
                continue
            case 'approved':
                // The caller clears the pending approval once it has stored the value, so a failed
                // save can still be retried with `--wait`.
                return outcome.value
            case 'rejected':
                return fail(
                    new HogError(
                        `${flow.noun}_rejected`,
                        `The ${flow.noun} was rejected in the browser.`,
                        `Run \`${flow.command}\` to start again.`
                    )
                )
            case 'expired':
                return fail(expired(flow))
        }
    }
    return fail(expired(flow))
}

function expired(flow: { noun: string; command: string }): HogError {
    return new HogError(
        `${flow.noun}_expired`,
        `The ${flow.noun} request expired before it was approved.`,
        `Run \`${flow.command}\` to start a new one.`
    )
}

function pendingResult(flow: { command: string }, pending: PendingApproval): ApprovalResult<never> {
    const code = pending.userCode ?? null
    const approve = code ? `open ${pending.url} and approve the code ${code}` : `open ${pending.url} and approve it`
    return {
        status: 'pending',
        url: pending.url,
        code,
        expiresAt: new Date(pending.expiresAt).toISOString(),
        instructions: `Ask the user to ${approve}. Then run \`${flow.command} --wait\`, which returns once they approve. If it times out, run it again.`,
        next: `${flow.command} --wait`,
    }
}

async function withSpinner<Value>(spinner: Spinner | undefined, noun: string, wait: Promise<Value>): Promise<Value> {
    try {
        const value = await wait
        spinner?.stop('Approved')
        return value
    } catch (error) {
        spinner?.error(`The ${noun} didn't finish`)
        throw error
    }
}

// Starts a command that waits for a person. At a terminal it shows the link, opens the browser when it
// can, and waits; Ctrl-C keeps the pending item for `--wait`. Agents and scripts get the link and the
// `--wait` command to run next, without waiting.
export async function runApproval<Pending extends PendingApproval, Value>(
    ctx: Context,
    flow: ApprovalFlow<Pending, Value>
): Promise<ApprovalResult<Value>> {
    const { runtime } = ctx
    const prompts = ctx.prompts
    const pending = await startPending(runtime, flow)
    if (!prompts) {
        return pendingResult(flow, pending)
    }
    const code = pending.userCode ? `\n\nCode: ${escapeControls(pending.userCode)}` : ''
    prompts.note(`${escapeControls(pending.url)}${code}`, `Approve the ${flow.noun} in your browser`)
    // Over SSH, a browser would open on the remote machine, where nobody sees it.
    const overSsh = runtime.env.SSH_CONNECTION !== undefined || runtime.env.SSH_TTY !== undefined
    const opened = !overSsh && (await runtime.openUrl(pending.url))
    const spinner = prompts.spinner(
        opened ? 'Waiting for you to approve in the browser' : 'Open the link above to approve. Waiting'
    )
    return { status: 'approved', value: await withSpinner(spinner, flow.noun, waitFor(runtime, flow, pending)) }
}

// `<command> --wait`: resumes the command's pending item. It takes no ID, because the item is on disk.
export async function resumeApproval<Pending extends PendingApproval, Value>(
    ctx: Context,
    flow: ApprovalWait<Pending, Value>
): Promise<Value> {
    const pending = await readPending(ctx.runtime, flow)
    if (!pending) {
        throw new HogError(
            `no_pending_${flow.noun}`,
            `No ${flow.noun} is waiting for approval.`,
            `Run \`${flow.command}\` to start one.`
        )
    }
    const spinner = ctx.prompts?.spinner(`Waiting for the ${flow.noun} to be approved in the browser`)
    return withSpinner(spinner, flow.noun, waitFor(ctx.runtime, flow, pending))
}

// What a person sees when an agent or a script started the request.
export function printPending(out: Output, result: Extract<ApprovalResult<unknown>, { status: 'pending' }>): void {
    out.line(
        result.code
            ? `Open this link to approve, and check that it shows the code ${out.style(escapeControls(result.code), 'bold')}:`
            : 'Open this link to approve:'
    )
    out.line(`  ${escapeControls(result.url)}`)
    out.line(`Then run ${out.style(result.next, 'bold')}.`)
}
