import { randomUUID } from 'crypto'
import { z } from 'zod'

import { Duration, durationMs } from '../duration'

const RecipientMatch = z.object({ recipient: z.string().optional() }).strict()
const HostMatch = z.object({ host: z.string().optional() }).strict()

export const SesThrottleParams = z.object({ rate: z.number().int().min(1) }).strict()

const Dose = z.union([
    z.object({ count: z.number().int().min(1) }).strict(),
    z.object({ share: z.number().gt(0).max(1) }).strict(),
])

export const CardFault = z.discriminatedUnion('name', [
    z
        .object({
            name: z.literal('ses.reject'),
            params: z.object({ type: z.enum(['rejected', 'bounce']) }).strict(),
            match: RecipientMatch.optional(),
            dose: Dose,
            for: Duration.optional(),
        })
        .strict(),
    z
        .object({
            name: z.literal('ses.throttle'),
            params: SesThrottleParams,
            match: RecipientMatch.optional(),
            for: Duration.optional(),
        })
        .strict(),
    z
        .object({
            name: z.literal('dest.status'),
            params: z.object({ code: z.number().int().min(200).max(599) }).strict(),
            match: HostMatch.optional(),
            dose: Dose,
            for: Duration.optional(),
        })
        .strict(),
])
export type CardFault = z.infer<typeof CardFault>

export type SesStatusAnswer = { status: number; type: string; message: string }

export type SesAnswer =
    | { kind: 'status'; answer: SesStatusAnswer }
    | { kind: 'bounce' }
    | { kind: 'drop-connection' }
    | { kind: 'no-answer' }
    | { kind: 'stalled-body' }

export type WebhookAnswer = { kind: 'webhook-status'; status: number }

export type FaultRule = {
    name: string
    answer: SesAnswer | WebhookAnswer
    match?: { recipient?: string; host?: string }
    dose: z.infer<typeof Dose> | { perSecond: number }
    for?: string
}

type FaultedRequest = { channel: 'ses'; recipients: string[] } | { channel: 'webhook'; host: string }

const REJECTED: SesStatusAnswer = { status: 400, type: 'MessageRejected', message: 'Message rejected' }
const THROTTLED: SesStatusAnswer = {
    status: 429,
    type: 'TooManyRequestsException',
    message: 'Maximum sending rate exceeded.',
}
const RATE_WINDOW_MS = 1000

export function ruleOf(fault: CardFault): FaultRule {
    switch (fault.name) {
        case 'ses.reject':
            return {
                ...fault,
                answer: fault.params.type === 'bounce' ? { kind: 'bounce' } : { kind: 'status', answer: REJECTED },
            }
        case 'ses.throttle':
            return { ...fault, dose: { perSecond: fault.params.rate }, answer: { kind: 'status', answer: THROTTLED } }
        case 'dest.status':
            return { ...fault, answer: { kind: 'webhook-status', status: fault.params.code } }
    }
}

type ActiveFault = {
    id: string
    rule: FaultRule
    until: number
    matched: number
    applied: number
    passedAt: number[]
}

const SHARE_TOLERANCE = 1e-9

function matches({ answer, match }: FaultRule, request: FaultedRequest): boolean {
    if (request.channel === 'webhook') {
        return answer.kind === 'webhook-status' && (match?.host === undefined || match.host === request.host)
    }
    return (
        answer.kind !== 'webhook-status' &&
        (match?.recipient === undefined || request.recipients.includes(match.recipient))
    )
}

function doseTakes(fault: ActiveFault, now: number): boolean {
    const {
        rule: { dose },
        matched,
        applied,
    } = fault
    if ('perSecond' in dose) {
        fault.passedAt = fault.passedAt.filter((at) => at > now - RATE_WINDOW_MS)
        return fault.passedAt.length >= dose.perSecond
    }
    if ('count' in dose) {
        return applied < dose.count
    }
    const crossings = (sends: number): number => Math.floor(sends * dose.share + SHARE_TOLERANCE)
    return crossings(matched) > crossings(matched - 1)
}

function countSentAgainst(throttles: ActiveFault[], now: number): void {
    for (const throttle of throttles) {
        throttle.passedAt.push(now)
    }
}

export class FaultList {
    private faults: ActiveFault[] = []

    add(rule: FaultRule): string {
        const id = randomUUID()
        const until = rule.for === undefined ? Infinity : Date.now() + durationMs(rule.for)
        this.faults.push({ id, rule, until, matched: 0, applied: 0, passedAt: [] })
        return id
    }

    remove(id: string): boolean {
        const before = this.faults.length
        this.faults = this.faults.filter((fault) => fault.id !== id)
        return this.faults.length < before
    }

    clear(): void {
        this.faults = []
    }

    applied(id: string): number {
        return this.faults.find((fault) => fault.id === id)?.applied ?? 0
    }

    takeSes(recipients: string[]): { name: string; answer: SesAnswer } | undefined {
        const rule = this.take({ channel: 'ses', recipients })
        return rule && rule.answer.kind !== 'webhook-status' ? { name: rule.name, answer: rule.answer } : undefined
    }

    takeWebhook(host: string): { name: string; status: number } | undefined {
        const rule = this.take({ channel: 'webhook', host })
        return rule?.answer.kind === 'webhook-status' ? { name: rule.name, status: rule.answer.status } : undefined
    }

    private take(request: FaultedRequest): FaultRule | undefined {
        const now = Date.now()
        this.faults = this.faults.filter((fault) => fault.until > now)
        const matching = this.faults.filter((fault) => matches(fault.rule, request))
        const throttles = matching.filter((fault) => 'perSecond' in fault.rule.dose)
        const answering = [...throttles, ...matching.filter((fault) => !throttles.includes(fault))].find((fault) => {
            fault.matched += 1
            return doseTakes(fault, now)
        })
        if (answering) {
            answering.applied += 1
        }
        if (answering === undefined || answering.rule.answer.kind === 'bounce') {
            countSentAgainst(
                throttles.filter((fault) => fault !== answering),
                now
            )
        }
        return answering?.rule
    }
}
