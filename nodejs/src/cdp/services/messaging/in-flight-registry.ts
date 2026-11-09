import { AsyncLocalStorage } from 'node:async_hooks'
import { totalmem } from 'node:os'
import { getHeapStatistics } from 'node:v8'
import { Counter, Gauge } from 'prom-client'

import { EmailAttachmentMetadata } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocation } from '~/cdp/types'

const MIB = 1024 * 1024
const EMAIL_MESSAGE_MAX_BYTES = 40_000_000
export const LARGEST_SEND_FILE_BYTES = (EMAIL_MESSAGE_MAX_BYTES * 3) / 4
// The raw bytes sit outside the V8 heap. The Base64 copy and the JSON body the SES client builds sit on it. Email text
// outside Latin-1 makes V8 store that body at two bytes per character, Base64 included, which the reservation covers.
const RESERVED_BYTES_PER_FILE_BYTE = 7
const HEAP_BYTES_PER_FILE_BYTE = 3
const BYTES_PER_SEND = 2 * MIB
const PLAIN_BATCH_ALLOWANCE_BYTES = 512 * MIB
const FIRST_DEFERRAL_MS = 5_000
const LONGEST_DEFERRAL_MS = 120_000

export type DeferralReason = 'over_budget' | 'over_heap' | 'at_cap' | 'refused'

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

export type InFlightLimits = { budgetBytes: number; heapLimitBytes: number; maxInFlight: number }

export type SendsWithFilesSettings = { memoryFraction: number; maxInFlight: number; heartbeatIntervalMs: number }

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

// Node reports no container limit as 0 or as a value past the machine's memory, depending on the version.
const podMemoryBytes = ({ constrainedBytes, totalBytes }: MachineMemory): number =>
    constrainedBytes > 0 && constrainedBytes < totalBytes ? constrainedBytes : totalBytes

export function inFlightLimitsFor(
    settings: SendsWithFilesSettings,
    machine: MachineMemory = machineMemory()
): { limits: InFlightLimits } | { refusal: string } {
    const largest = estimateSend(LARGEST_SEND_FILE_BYTES)
    const budgetBytes = Math.floor(settings.memoryFraction * (podMemoryBytes(machine) - PLAIN_BATCH_ALLOWANCE_BYTES))
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

export function fileBytesOf(invocation: CyclotronJobInvocation): number | null {
    const sent = (invocation.state as { send?: { attachments?: readonly EmailAttachmentMetadata[] } } | null)?.send
    const queued = invocation.queueParameters?.type === 'email' ? invocation.queueParameters.attachments : undefined
    const files = sent?.attachments ?? queued
    return files?.length ? declaredFileBytes(files) : null
}

export const declaredFileBytes = (files: readonly EmailAttachmentMetadata[]): number =>
    files.reduce((total, file) => total + file.sizeBytes, 0)

export const exceedsLargestSend = (fileBytes: number): boolean => fileBytes > LARGEST_SEND_FILE_BYTES

export function deferralDelayMs(earlierDeferrals: number, random: () => number = Math.random): number {
    const ceiling = Math.min(LONGEST_DEFERRAL_MS, FIRST_DEFERRAL_MS * 2 ** earlierDeferrals)
    return Math.max(FIRST_DEFERRAL_MS, ceiling / 2 + (random() * ceiling) / 2)
}

const sendCalls = new AsyncLocalStorage<Set<Promise<unknown>>>()

// A send's call holds its bytes until it settles, even after the send stopped waiting for it on a deadline or on a
// sibling call's failure.
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

    // Admission is synchronous, so the sends of one batch cannot all pass the check before any of them reserves.
    public tryStart<T>(
        fileBytes: number,
        send: () => Promise<T>
    ): { started: Promise<T> } | { deferred: DeferralReason } {
        const reason = this.whyNoRoom(fileBytes)
        if (reason) {
            deferralTokensSpent.labels({ reason }).inc()
            return { deferred: reason }
        }
        const estimate = estimateSend(fileBytes)
        this.hold(estimate, 1)
        // The send settles at its result write. Its reservation stays until its calls settle, which has no deadline, so
        // nothing that waits for the send waits for them.
        const started = sendCalls.run(new Set(), async () => {
            try {
                return await send()
            } finally {
                void everyCallSettled().then(() => this.hold(estimate, -1))
            }
        })
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
