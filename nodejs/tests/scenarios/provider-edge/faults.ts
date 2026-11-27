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
    z
        .object({
            name: z.literal('pg.enqueue_refused'),
            dose: Dose,
            for: Duration.optional(),
        })
        .strict(),
    z
        .object({
            name: z.literal('pg.commit_reply_lost'),
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
    | { kind: 'accepted-then-status'; answer: SesStatusAnswer }
    | { kind: 'hold-answer' }

export type WebhookAnswer =
    | { kind: 'webhook-status'; status: number }
    | { kind: 'webhook-ambiguous'; accepted: boolean }

// Postgres itself refuses the insert, so its error, the transaction it fails and the rest of the client's pipeline
// are the server's own.
export type PgAnswer = { kind: 'pg-refuse' } | { kind: 'pg-commit-reply-lost' }

type Answer = SesAnswer | WebhookAnswer | PgAnswer

export type FaultRule = {
    name: string
    answer: Answer
    match?: { recipient?: string; host?: string }
    dose: z.infer<typeof Dose> | { perSecond: number }
    for?: string
    pick?: string
}

type FaultedRequest =
    | { channel: 'ses'; recipients: string[] }
    | { channel: 'webhook'; host: string }
    | { channel: 'pg'; at: 'enqueue' | 'commit' }

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
        case 'pg.enqueue_refused':
            return { ...fault, answer: { kind: 'pg-refuse' } }
        case 'pg.commit_reply_lost':
            return { ...fault, answer: { kind: 'pg-commit-reply-lost' } }
    }
}

export const heldAnswerRule = (share?: number): FaultRule => ({
    name: 'edge.accepted',
    answer: { kind: 'hold-answer' },
    dose: share === undefined ? { count: 1 } : { share },
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

// The proxy names a refused enqueue's table after the fault's token, so Postgres's own error names the fault it
// answers, and a clear forgets the tokens it handed out.
const tokenOf = (faultId: string): string => faultId.replaceAll('-', '')

// An enqueue carries no unit the edge can read, so a Postgres fault records no hit.
const PG_HIT: Hit = { pickKey: 'pg' }

const isWebhookAnswer = (answer: Answer): answer is WebhookAnswer =>
    answer.kind === 'webhook-status' || answer.kind === 'webhook-ambiguous'

const isPgAnswer = (answer: Answer): answer is PgAnswer =>
    answer.kind === 'pg-refuse' || answer.kind === 'pg-commit-reply-lost'

const isSesAnswer = (answer: Answer): answer is SesAnswer => !isWebhookAnswer(answer) && !isPgAnswer(answer)

const reachesSes = (answer: Answer): boolean =>
    answer.kind === 'bounce' ||
    answer.kind === 'hold-answer' ||
    answer.kind === 'accepted-then-status' ||
    (answer.kind === 'ambiguous' && answer.accepted)

function matches({ answer, match }: FaultRule, request: FaultedRequest): boolean {
    if (request.channel === 'webhook') {
        return isWebhookAnswer(answer) && (match?.host === undefined || match.host === request.host)
    }
    if (request.channel === 'pg') {
        return answer.kind === (request.at === 'enqueue' ? 'pg-refuse' : 'pg-commit-reply-lost')
    }
    return isSesAnswer(answer) && (match?.recipient === undefined || request.recipients.includes(match.recipient))
}

function doseTakes(fault: ActiveFault, now: number, { unitId, pickKey }: Hit): boolean {
    const {
        rule: { answer, dose, pick },
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
    if (answer.kind === 'hold-answer' && (applied > 0 || unitId === undefined)) {
        return false
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
    private refusing = new Map<string, string>()

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
        this.refusing.clear()
    }

    firstAppliedAt(id: string): number | undefined {
        return this.firstApplied.get(id)
    }

    hitsOf(id: string): string[] {
        return [...(this.hits.get(id) ?? [])]
    }

    takeSes(recipients: string[], hit: Hit): { id: string; name: string; answer: SesAnswer } | undefined {
        const fault = this.take({ channel: 'ses', recipients }, hit)
        return fault && isSesAnswer(fault.rule.answer)
            ? { id: fault.id, name: fault.rule.name, answer: fault.rule.answer }
            : undefined
    }

    takeWebhook(host: string, hit: Hit): { name: string; answer: WebhookAnswer } | undefined {
        const rule = this.take({ channel: 'webhook', host }, hit)?.rule
        return rule && isWebhookAnswer(rule.answer) ? { name: rule.name, answer: rule.answer } : undefined
    }

    refusePg(): string | undefined {
        const fault = this.take({ channel: 'pg', at: 'enqueue' }, PG_HIT, { appliesNow: false })
        if (fault === undefined) {
            return undefined
        }
        this.refusing.set(tokenOf(fault.id), fault.id)
        return tokenOf(fault.id)
    }

    // Marks the fault observed once Postgres's answer to a refused enqueue passes the edge on its way to the client.
    pgRefusalAnswered(token: string): void {
        const id = this.refusing.get(token)
        if (id !== undefined && !this.firstApplied.has(id)) {
            this.firstApplied.set(id, Date.now())
        }
    }

    // The proxy cuts the client as soon as this answers, so the fault is observed when it takes its dose.
    losePgCommitReply(): boolean {
        return this.take({ channel: 'pg', at: 'commit' }, PG_HIT) !== undefined
    }

    private take(request: FaultedRequest, hit: Hit, { appliesNow = true } = {}): ActiveFault | undefined {
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
            if (appliesNow && !this.firstApplied.has(answering.id)) {
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
