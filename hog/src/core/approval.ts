import { z } from 'zod'

import { ApiError } from '@/posthog/api'

import type { Context } from './context'
import { HogError } from './errors'
import { parseJsonOrUndefined } from './json'
import { escapeControls, type Output } from './output'
import { hogFile } from './paths'
import type { Spinner } from './prompts'
import type { Runtime } from './runtime'
import type { Schema } from './schema'

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

// Which pending item a flow keeps, and the commands that start and resume it.
export interface ApprovalIdentity {
    // The command that starts it, like `hog auth login`.
    command: string
    // The command that waits for it, like `hog auth login --wait`.
    resume: string
    // Names the pending item's file. A command that keeps one item per folder adds the folder to it,
    // and `clearPendingFor` clears every item whose name starts the same way.
    pendingName: string
}

// For a command that keeps one pending item and resumes it with `<command> --wait`.
export function waitIdentity(command: string): ApprovalIdentity {
    return { command, resume: `${command} --wait`, pendingName: command }
}

// One command that waits for a person. Every such command goes through `runApproval`, so they all
// start, wait, resume and give up the same way.
export interface ApprovalFlow<Pending extends PendingApproval, Value> extends ApprovalIdentity {
    // What the person approves, in copy and in error codes, like `login`.
    noun: string
    // The command to start over after a rejection or expiry, when `command` alone can't ask for the
    // same thing again. Agents run it as written.
    restart?: (pending: Pending) => string
    // Reads the pending item back from its file. An item hog can't read counts as none.
    pending: Schema<Pending>
    start: () => Promise<Pending>
    // Whether a pending item from an earlier run can stand in for a new one, so an agent that
    // retries hands the person the link it already shared.
    reuse?: (existing: Pending) => boolean
    // Rechecks a reused item someone may have resolved in the browser. Undefined starts a new one.
    refresh?: (existing: Pending) => Promise<Pending | undefined>
    // Who approves when the person at the terminal can't, so hog hands over the link instead of waiting.
    // Admins set their own names, so `names` never go into the instructions an agent follows.
    approver?: (pending: Pending) => { who: string; names: string[] } | undefined
    // `timeoutMs` is how long the poll request may take before the request expires.
    poll: (pending: Pending, timeoutMs: number) => Promise<PollOutcome<Value>>
    // Caps one wait for a request that stays open for days, so an agent never blocks on a person for long.
    maxWaitMs?: number
    checkResumable?: (pending: Pending) => void
}

// What resuming a pending item needs. It can't start a new one.
export type ApprovalWait<Pending extends PendingApproval, Value> = Pick<
    ApprovalFlow<Pending, Value>,
    'command' | 'resume' | 'pendingName' | 'noun' | 'pending' | 'poll' | 'maxWaitMs' | 'checkResumable' | 'restart'
>

export type ApprovalResult<Value> =
    | {
          status: 'pending'
          url: string
          code: string | null
          expiresAt: string
          instructions: string
          next: string
          approver?: string
          approverNames?: string[]
      }
    | { status: 'approved'; value: Value }

const MAX_RETRIES = 3
const REQUEST_TIMEOUT_MS = 30_000
// RFC 8628 asks clients to poll this much slower after each `slow_down`.
const SLOW_DOWN_SECONDS = 5
// Reusing a request this close to expiry would hand the person a link that dies while they open it.
// Approving takes a few seconds, so the margin stays short.
const REUSE_MARGIN_MS = 20_000

function errorCode(noun: string): string {
    return noun.replaceAll(' ', '_')
}

function pendingStem(name: string): string {
    return `pending-${name.replace(/^hog /, '').replaceAll(' ', '-')}`
}

function pendingPath(runtime: Runtime, name: string): string {
    return hogFile(runtime, `${pendingStem(name)}.json`)
}

async function readPending<Pending extends PendingApproval>(
    runtime: Runtime,
    flow: ApprovalWait<Pending, unknown>
): Promise<Pending | undefined> {
    try {
        return parseJsonOrUndefined(await runtime.readFile(pendingPath(runtime, flow.pendingName)), flow.pending)
    } catch {
        return undefined
    }
}

export async function clearPending(runtime: Runtime, pendingName: string): Promise<void> {
    await runtime.removeFile(pendingPath(runtime, pendingName))
}

// Clears the item named `prefix` and every item whose name adds to it, such as each folder's.
export async function clearPendingFor(runtime: Runtime, prefix: string): Promise<void> {
    const stem = pendingStem(prefix)
    const names = await runtime.listFiles(hogFile(runtime, '')).catch(() => [])
    await Promise.all(
        names
            .filter((name) => name === `${stem}.json` || (name.startsWith(`${stem}-`) && name.endsWith('.json')))
            .map((name) => runtime.removeFile(hogFile(runtime, name)))
    )
}

// `marginMs` keeps a link that is about to expire from going to a person. A resume passes 0,
// because the person can have approved the item already.
export async function reusablePending<Pending extends PendingApproval, Value>(
    runtime: Runtime,
    flow: ApprovalFlow<Pending, Value>,
    marginMs = REUSE_MARGIN_MS
): Promise<Pending | undefined> {
    const existing = await readPending(runtime, flow)
    return existing && existing.expiresAt - runtime.now() > marginMs && flow.reuse?.(existing) ? existing : undefined
}

// A new start replaces the command's pending item, unless the flow can reuse it.
async function startPending<Pending extends PendingApproval, Value>(
    runtime: Runtime,
    flow: ApprovalFlow<Pending, Value>
): Promise<Pending> {
    const existing = await reusablePending(runtime, flow)
    if (existing) {
        const current = flow.refresh ? await flow.refresh(existing) : existing
        if (current) {
            await runtime.writePrivateFile(pendingPath(runtime, flow.pendingName), JSON.stringify(current))
            return current
        }
    }
    const pending = await flow.start()
    // The pending item can hold a secret, like a device code, so only its owner may read it.
    await runtime.writePrivateFile(pendingPath(runtime, flow.pendingName), JSON.stringify(pending))
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
            `${errorCode(flow.noun)}_interrupted`,
            `hog lost contact with PostHog while waiting for the ${flow.noun}: ${reason}`,
            `Run \`${flow.resume}\` to keep waiting. The link stays the same.`
        )
    const fail = async (error: HogError): Promise<never> => {
        await clearPending(runtime, flow.pendingName)
        throw error
    }

    let failures = 0
    let intervalSeconds = pending.intervalSeconds
    const giveUpAt = flow.maxWaitMs === undefined ? Infinity : runtime.now() + flow.maxWaitMs
    while (runtime.now() < pending.expiresAt) {
        if (runtime.now() >= giveUpAt) {
            throw new HogError(
                `${errorCode(flow.noun)}_still_pending`,
                `The ${flow.noun} is still waiting for approval.`,
                `Run \`${flow.resume}\` again later. The link stays the same.`
            )
        }
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
            if (!isTransient(error)) {
                // A lapsed login says nothing about the request, so it stays for `--wait` after `hog auth login`.
                if (error.code === 'session_expired') {
                    throw error
                }
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
                        `${errorCode(flow.noun)}_rejected`,
                        `The ${flow.noun} was rejected in the browser.`,
                        `Run \`${flow.restart?.(pending) ?? flow.command}\` to start again.`
                    )
                )
            case 'expired':
                return fail(expired(flow, pending))
        }
    }
    // PostHog keeps an approval given before the deadline.
    try {
        const last = await flow.poll(pending, REQUEST_TIMEOUT_MS)
        if (last.state === 'approved') {
            return last.value
        }
    } catch (error) {
        if (!(error instanceof HogError)) {
            throw error
        }
        if (isTransient(error)) {
            throw interrupted(error.message)
        }
        // As in the loop above, a lapsed login keeps the request for `--wait` after `hog auth login`.
        if (error.code === 'session_expired') {
            throw error
        }
    }
    return fail(expired(flow, pending))
}

function isTransient(error: HogError): boolean {
    return (
        error.code === 'network_error' ||
        error.code === 'refresh_failed' ||
        (error instanceof ApiError && (error.status === 429 || error.status >= 500))
    )
}

function expired<Pending extends PendingApproval>(
    flow: Pick<ApprovalWait<Pending, unknown>, 'noun' | 'command' | 'restart'>,
    pending: Pending
): HogError {
    return new HogError(
        `${errorCode(flow.noun)}_expired`,
        `The ${flow.noun} request expired before it was approved.`,
        `Run \`${flow.restart?.(pending) ?? flow.command}\` to start a new one.`
    )
}

export function pendingResult<Pending extends PendingApproval>(
    flow: Pick<ApprovalFlow<Pending, unknown>, 'resume' | 'approver'>,
    pending: Pending
): Extract<ApprovalResult<never>, { status: 'pending' }> {
    const code = pending.userCode ?? null
    const approver = flow.approver?.(pending)
    const approve = approver
        ? `send ${pending.url} to ${approver.who} to approve`
        : code
          ? `open ${pending.url} and approve the code ${code}`
          : `open ${pending.url} and approve it`
    return {
        status: 'pending',
        url: pending.url,
        code,
        expiresAt: new Date(pending.expiresAt).toISOString(),
        instructions: `Ask the person to ${approve}. Then run \`${flow.resume}\` yourself. It returns once they approve, and if it times out, run it again.`,
        next: flow.resume,
        ...(approver ? { approver: approver.who, approverNames: approver.names } : {}),
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

// Nobody approves anything in CI. Agents pass, because they hand the link to a person.
export function refuseInCi(ctx: Context, command: string, hint: string): void {
    if (!ctx.prompts && ctx.mode.agent === undefined && ctx.mode.ci) {
        throw new HogError(
            'login_needs_a_person',
            `${command} needs a person to approve it in a browser, so it does not run in CI.`,
            hint
        )
    }
}

export type PendingResult = Extract<ApprovalResult<never>, { status: 'pending' }>

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
    if (!prompts || flow.approver?.(pending) !== undefined) {
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
): Promise<{ pending: Pending; value: Value }> {
    const pending = await readPending(ctx.runtime, flow)
    if (!pending) {
        throw new HogError(
            `no_pending_${errorCode(flow.noun)}`,
            `No ${flow.noun} is waiting for approval.`,
            `Run \`${flow.command}\` to start one.`
        )
    }
    flow.checkResumable?.(pending)
    const spinner = ctx.prompts?.spinner(`Waiting for the ${flow.noun} to be approved in the browser`)
    return { pending, value: await withSpinner(spinner, flow.noun, waitFor(ctx.runtime, flow, pending)) }
}

// What a person sees when an agent or a script started the request.
export function printPending(out: Output, result: PendingResult): void {
    out.line(
        result.approver
            ? `Only ${escapeControls(result.approver)}${result.approverNames?.length ? ` (${escapeControls(result.approverNames.join(', '))})` : ''} can approve it. Send them this link:`
            : result.code
              ? `Open this link to approve, and check that it shows the code ${out.style(escapeControls(result.code), 'bold')}:`
              : 'Open this link to approve:'
    )
    out.line(`  ${escapeControls(result.url)}`)
    out.line(`Then run ${out.style(result.next, 'bold')}.`)
}
