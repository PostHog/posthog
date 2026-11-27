import { AsyncLocalStorage } from 'node:async_hooks'
import { totalmem } from 'node:os'
import { getHeapStatistics } from 'node:v8'
import { Counter, Gauge } from 'prom-client'

import { EmailAttachmentMetadata } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocation } from '~/cdp/types'

import { MESSAGE_MAX_BYTES } from './message-estimate'

const MIB = 1024 * 1024
export const LARGEST_SEND_FILE_BYTES = (MESSAGE_MAX_BYTES * 3) / 4
const RESERVED_BYTES_PER_FILE_BYTE = 7
const HEAP_BYTES_PER_FILE_BYTE = 3
const BYTES_PER_SEND = 2 * MIB
const PLAIN_BATCH_ALLOWANCE_BYTES = 512 * MIB
const FIRST_DEFERRAL_MS = 5_000
const LONGEST_DEFERRAL_MS = 120_000

const DEFERRAL_REASONS = ['over_budget', 'over_heap', 'at_cap', 'refused'] as const
export type DeferralReason = (typeof DEFERRAL_REASONS)[number]

declare const mintedByTheRegistry: unique symbol
export type Admission = {
    readonly files: readonly Readonly<EmailAttachmentMetadata>[]
    readonly [mintedByTheRegistry]: true
}
type UnadmittedReason = 'outside_any_admission' | 'released' | 'other_files'

const sendsInFlight = new Gauge({
    name: 'cdp_email_attachments_sends_in_flight',
    help: 'Sends with files that this email worker admitted and that have not released their memory reservation',
})

const reservedBytesInFlight = new Gauge({
    name: 'cdp_email_attachments_reserved_bytes',
    help: 'Memory that the sends with files in flight on this email worker hold in reservation',
})

export const deferralTokensSpent = new Counter({
    name: 'cdp_email_attachments_deferral_tokens_total',
    help: 'Sends with files that the email worker had no room for and deferred. Each one spent the SES rate-limit token its dequeue claimed without sending',
    labelNames: ['reason'],
})

for (const reason of DEFERRAL_REASONS) {
    deferralTokensSpent.labels({ reason }).inc(0)
}

const unadmittedLoads = new Counter({
    name: 'cdp_email_attachments_unadmitted_loads_total',
    help: 'Loads of attachment files that the email worker refused because no live admission reserved memory for exactly those files, by reason',
    labelNames: ['reason'],
})

export class AttachmentsNotAdmittedError extends Error {
    constructor(readonly reason: UnadmittedReason) {
        super(`The attachment files of this send hold no admission (${reason}), so they were not loaded`)
        this.name = 'AttachmentsNotAdmittedError'
    }
}

function refusedUnadmitted(reason: UnadmittedReason): AttachmentsNotAdmittedError {
    unadmittedLoads.labels({ reason }).inc()
    return new AttachmentsNotAdmittedError(reason)
}

export type InFlightLimits = { budgetBytes: number; heapLimitBytes: number; maxInFlight: number }

export type SendsWithFilesSettings = {
    memoryFraction: number
    maxInFlight: number
    heartbeatIntervalMs: number
    attachmentStoreBucket: string
}

export type MachineMemory = { constrainedBytes: number; totalBytes: number; heapLimitBytes: number }

const machineMemory = (): MachineMemory => ({
    constrainedBytes: process.constrainedMemory(),
    totalBytes: totalmem(),
    heapLimitBytes: getHeapStatistics().heap_size_limit,
})

export const estimateSend = (fileBytes: number): { reservedBytes: number; heapBytes: number } => ({
    reservedBytes: fileBytes * RESERVED_BYTES_PER_FILE_BYTE + BYTES_PER_SEND,
    heapBytes: fileBytes * HEAP_BYTES_PER_FILE_BYTE + BYTES_PER_SEND,
})

const podMemoryBytes = ({ constrainedBytes, totalBytes }: MachineMemory): number =>
    constrainedBytes > 0 && constrainedBytes < totalBytes ? constrainedBytes : totalBytes

export function inFlightLimitsFor(
    settings: SendsWithFilesSettings,
    machine: MachineMemory = machineMemory()
): { limits: InFlightLimits } | { refusal: string } {
    const largest = estimateSend(LARGEST_SEND_FILE_BYTES)
    const budgetBytes = Math.floor(settings.memoryFraction * (podMemoryBytes(machine) - PLAIN_BATCH_ALLOWANCE_BYTES))
    if (!settings.attachmentStoreBucket) {
        return { refusal: 'no attachment store is set, so the worker cannot load the files' }
    }
    if (settings.heartbeatIntervalMs <= 0) {
        return { refusal: 'the job heartbeat is off, so a send that outlives its batch would be reset and sent twice' }
    }
    if (settings.maxInFlight < 1) {
        return { refusal: 'the in-flight cap is below one send' }
    }
    if (budgetBytes < largest.reservedBytes) {
        return { refusal: `the memory budget of ${budgetBytes} bytes cannot hold one message at the size limit` }
    }
    if (machine.heapLimitBytes < largest.heapBytes) {
        return {
            refusal: `the heap limit of ${machine.heapLimitBytes} bytes cannot hold one message at the size limit`,
        }
    }
    return { limits: { budgetBytes, heapLimitBytes: machine.heapLimitBytes, maxInFlight: settings.maxInFlight } }
}

export function filesOf(invocation: CyclotronJobInvocation): readonly EmailAttachmentMetadata[] | null {
    const files =
        invocation.queueParameters?.type === 'email'
            ? invocation.queueParameters.attachments
            : (invocation.state as { send?: { attachments?: readonly EmailAttachmentMetadata[] } } | null)?.send
                  ?.attachments
    return files?.length ? files : null
}

export const declaredFileBytes = (files: readonly EmailAttachmentMetadata[]): number =>
    files.reduce((total, file) => total + file.sizeBytes, 0)

export const exceedsLargestSend = (fileBytes: number): boolean => fileBytes > LARGEST_SEND_FILE_BYTES

export const firstDueAt = (invocation: CyclotronJobInvocation, now: number): number =>
    invocation.queueMetadata?.attachmentDueAt ?? invocation.queueScheduledAt?.toMillis() ?? now

export function deferralDelayMs(earlierDeferrals: number, random: () => number = Math.random): number {
    const ceiling = Math.min(LONGEST_DEFERRAL_MS, FIRST_DEFERRAL_MS * 2 ** earlierDeferrals)
    return Math.max(FIRST_DEFERRAL_MS, ceiling / 2 + (random() * ceiling) / 2)
}

const sendCalls = new AsyncLocalStorage<Set<Promise<unknown>>>()
const sendAdmission = new AsyncLocalStorage<Admission>()
const liveAdmissions = new WeakSet<Admission>()

export function requireAdmission(files: readonly EmailAttachmentMetadata[]): Admission {
    const admission = sendAdmission.getStore()
    if (!admission) {
        throw refusedUnadmitted('outside_any_admission')
    }
    if (!sameFiles(admittedFiles(admission), files)) {
        throw refusedUnadmitted('other_files')
    }
    return admission
}

export function admittedFiles(admission: Admission): readonly Readonly<EmailAttachmentMetadata>[] {
    if (!liveAdmissions.has(admission)) {
        throw refusedUnadmitted('released')
    }
    if (sendAdmission.getStore() !== admission) {
        throw refusedUnadmitted('outside_any_admission')
    }
    return admission.files
}

const sameFiles = (admitted: readonly EmailAttachmentMetadata[], files: readonly EmailAttachmentMetadata[]): boolean =>
    admitted.length === files.length &&
    admitted.every(
        (file, at) =>
            file.sha256 === files[at].sha256 &&
            file.sizeBytes === files[at].sizeBytes &&
            file.filename === files[at].filename &&
            file.contentType === files[at].contentType &&
            file.contentId === files[at].contentId
    )

export function settledBeforeAbort<T>(signal: AbortSignal, promise: Promise<T>): Promise<T> {
    return new Promise<T>((resolve, reject) => {
        const abort = (): void => reject(signal.reason)
        promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort))
        if (signal.aborted) {
            abort()
        } else {
            signal.addEventListener('abort', abort, { once: true })
        }
    })
}

export function holdUntilSettled(call: Promise<unknown>): void {
    const calls = sendCalls.getStore()
    if (!calls) {
        return
    }
    calls.add(call)
    const forget = (): void => void calls.delete(call)
    call.then(forget, forget)
}

export async function callsSettledWithin(maxWaitMs: number): Promise<void> {
    const calls = sendCalls.getStore()
    if (!calls?.size) {
        return
    }
    let timer: NodeJS.Timeout | undefined
    await Promise.race([
        Promise.allSettled([...calls]),
        new Promise((resolve) => {
            timer = setTimeout(resolve, maxWaitMs)
        }),
    ])
    clearTimeout(timer)
}

export async function callsSettledBefore(deadline: AbortSignal): Promise<void> {
    if (!sendCalls.getStore()?.size) {
        return
    }
    await new Promise<void>((resolve, reject) => {
        const abort = (): void => reject(deadline.reason)
        void everyCallSettled()
            .then(resolve)
            .finally(() => deadline.removeEventListener('abort', abort))
        if (deadline.aborted) {
            abort()
        } else {
            deadline.addEventListener('abort', abort, { once: true })
        }
    })
}

async function everyCallSettled(): Promise<void> {
    const calls = sendCalls.getStore()
    while (calls?.size) {
        await Promise.allSettled([...calls])
    }
}

export class InFlightRegistry {
    private reservedBytes = 0
    private heapBytes = 0
    private inFlight = 0

    constructor(
        private readonly limits: InFlightLimits | null,
        private readonly heapUsedBytes: () => number = () => process.memoryUsage().heapUsed
    ) {}

    public tryStart<T>(
        files: readonly EmailAttachmentMetadata[],
        send: () => Promise<T>
    ): { started: Promise<T> } | { deferred: DeferralReason } {
        const admitted = Object.freeze(files.map((file) => Object.freeze({ ...file })))
        const fileBytes = declaredFileBytes(admitted)
        const reason = this.whyNoRoom(fileBytes)
        if (reason) {
            deferralTokensSpent.labels({ reason }).inc()
            return { deferred: reason }
        }
        const estimate = estimateSend(fileBytes)
        this.hold(estimate, 1)
        const admission = Object.freeze({ files: admitted }) as Admission
        liveAdmissions.add(admission)
        const started = sendAdmission.run(admission, () =>
            sendCalls.run(new Set(), async () => {
                try {
                    return await send()
                } finally {
                    liveAdmissions.delete(admission)
                    void everyCallSettled().then(() => this.hold(estimate, -1))
                }
            })
        )
        return { started }
    }

    private whyNoRoom(fileBytes: number): DeferralReason | null {
        if (!this.limits) {
            return 'refused'
        }
        if (this.inFlight >= this.limits.maxInFlight) {
            return 'at_cap'
        }
        const estimate = estimateSend(fileBytes)
        if (this.reservedBytes + estimate.reservedBytes > this.limits.budgetBytes) {
            return 'over_budget'
        }
        if (this.heapUsedBytes() + this.heapBytes + estimate.heapBytes > this.limits.heapLimitBytes) {
            return 'over_heap'
        }
        return null
    }

    private hold(estimate: { reservedBytes: number; heapBytes: number }, sends: 1 | -1): void {
        this.inFlight += sends
        this.reservedBytes += sends * estimate.reservedBytes
        this.heapBytes += sends * estimate.heapBytes
        sendsInFlight.set(this.inFlight)
        reservedBytesInFlight.set(this.reservedBytes)
    }
}
