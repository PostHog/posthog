import { createHash, randomUUID } from 'crypto'
import { z } from 'zod'

import { Duration, durationMs } from '../duration'

const RecipientMatch = z.object({ recipient: z.string().optional() }).strict()
const HostMatch = z.object({ host: z.string().optional() }).strict()

export const SesThrottleParams = z.object({ rate: z.number().int().min(1) }).strict()

export const SesRejectParams = z.object({ type: z.enum(['rejected', 'bounce']) }).strict()

export const AmbiguousParams = z.object({ accepted: z.boolean() }).strict()

const Dose = z.union([
    z.object({ count: z.number().int().min(1) }).strict(),
    z.object({ share: z.number().gt(0).max(1) }).strict(),
])

export const CardFault = z.discriminatedUnion('name', [
    z
        .object({
            name: z.literal('ses.reject'),
            params: SesRejectParams,
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
    z
        .object({
            name: z.literal('ses.ambiguous'),
            params: AmbiguousParams,
            match: RecipientMatch.optional(),
            dose: Dose,
            for: Duration.optional(),
        })
        .strict(),
    z
        .object({
            name: z.literal('dest.ambiguous'),
            params: AmbiguousParams,
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
    | { kind: 'ambiguous'; accepted: boolean }
    | { kind: 'hold-answer' }

export type WebhookAnswer =
    | { kind: 'webhook-status'; status: number }
    | { kind: 'webhook-ambiguous'; accepted: boolean }

export type FaultRule = {
    name: string
    answer: SesAnswer | WebhookAnswer
    match?: { recipient?: string; host?: string }
    dose: z.infer<typeof Dose> | { perSecond: number }
    for?: string
    pick?: string
}

type FaultedRequest = { channel: 'ses'; recipients: string[] } | { channel: 'webhook'; host: string }

export type Hit = { unitId?: string; pickKey: string }

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
        case 'ses.ambiguous':
            return { ...fault, answer: { kind: 'ambiguous', accepted: fault.params.accepted } }
        case 'dest.ambiguous':
            return { ...fault, answer: { kind: 'webhook-ambiguous', accepted: fault.params.accepted } }
    }
}

export const heldAnswerRule = (): FaultRule => ({
    name: 'edge.accepted',
    answer: { kind: 'hold-answer' },
    dose: { count: 1 },
})

type ActiveFault = {
    id: string
    rule: FaultRule
    until: number
    matched: number
    applied: number
    passedAt: number[]
    attempts: Map<string, number>
}

const SHARE_TOLERANCE = 1e-9
const SCORE_BYTES = 6

const ORDINAL_AT_END_OF_UNIT_ID = /-(\d+)$/

export function hitOf(unitId: string | undefined, fallback: string): Hit {
    return unitId === undefined
        ? { pickKey: fallback }
        : { unitId, pickKey: ORDINAL_AT_END_OF_UNIT_ID.exec(unitId)?.[1] ?? unitId }
}

function picked(pick: string, key: string, attempt: number, share: number): boolean {
    const digest = createHash('sha256').update(`${pick}\0${key}\0${attempt}`).digest()
    return digest.readUIntBE(0, SCORE_BYTES) / 2 ** (8 * SCORE_BYTES) < share
}

const isWebhookAnswer = (answer: SesAnswer | WebhookAnswer): answer is WebhookAnswer =>
    answer.kind === 'webhook-status' || answer.kind === 'webhook-ambiguous'

const reachesSes = (answer: SesAnswer | WebhookAnswer): boolean =>
    answer.kind === 'bounce' || answer.kind === 'hold-answer' || (answer.kind === 'ambiguous' && answer.accepted)

function matches({ answer, match }: FaultRule, request: FaultedRequest): boolean {
    if (request.channel === 'webhook') {
        return isWebhookAnswer(answer) && (match?.host === undefined || match.host === request.host)
    }
    return !isWebhookAnswer(answer) && (match?.recipient === undefined || request.recipients.includes(match.recipient))
}

function doseTakes(fault: ActiveFault, now: number, { unitId, pickKey }: Hit): boolean {
    const {
        rule: { dose, pick },
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
    if (pick !== undefined) {
        const attempt = fault.attempts.get(unitId ?? pickKey) ?? 0
        fault.attempts.set(unitId ?? pickKey, attempt + 1)
        return picked(pick, pickKey, attempt, dose.share)
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
    private firstApplied = new Map<string, number>()
    private hits = new Map<string, Set<string>>()

    add(rule: FaultRule): string {
        const id = randomUUID()
        const until = rule.for === undefined ? Infinity : Date.now() + durationMs(rule.for)
        this.faults.push({ id, rule, until, matched: 0, applied: 0, passedAt: [], attempts: new Map() })
        return id
    }

    remove(id: string): boolean {
        const before = this.faults.length
        this.faults = this.faults.filter((fault) => fault.id !== id)
        return this.faults.length < before
    }

    clear(): void {
        this.faults = []
        this.firstApplied.clear()
        this.hits.clear()
    }

    firstAppliedAt(id: string): number | undefined {
        return this.firstApplied.get(id)
    }

    hitsOf(id: string): string[] {
        return [...(this.hits.get(id) ?? [])]
    }

    takeSes(recipients: string[], hit: Hit): { id: string; name: string; answer: SesAnswer } | undefined {
        const fault = this.take({ channel: 'ses', recipients }, hit)
        return fault && !isWebhookAnswer(fault.rule.answer)
            ? { id: fault.id, name: fault.rule.name, answer: fault.rule.answer }
            : undefined
    }

    takeWebhook(host: string, hit: Hit): { name: string; answer: WebhookAnswer } | undefined {
        const rule = this.take({ channel: 'webhook', host }, hit)?.rule
        return rule && isWebhookAnswer(rule.answer) ? { name: rule.name, answer: rule.answer } : undefined
    }

    private take(request: FaultedRequest, hit: Hit): ActiveFault | undefined {
        const now = Date.now()
        this.faults = this.faults.filter((fault) => fault.until > now)
        const matching = this.faults.filter((fault) => matches(fault.rule, request))
        const throttles = matching.filter((fault) => 'perSecond' in fault.rule.dose)
        const answering = [...throttles, ...matching.filter((fault) => !throttles.includes(fault))].find((fault) => {
            fault.matched += 1
            return doseTakes(fault, now, hit)
        })
        if (answering) {
            answering.applied += 1
            if (hit.unitId !== undefined) {
                this.hits.set(answering.id, (this.hits.get(answering.id) ?? new Set()).add(hit.unitId))
            }
            if (!this.firstApplied.has(answering.id)) {
                this.firstApplied.set(answering.id, now)
            }
        }
        if (answering === undefined || reachesSes(answering.rule.answer)) {
            countSentAgainst(
                throttles.filter((fault) => fault !== answering),
                now
            )
        }
        return answering
    }
}
