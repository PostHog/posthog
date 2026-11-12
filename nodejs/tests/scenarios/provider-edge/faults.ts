import { randomUUID } from 'crypto'
import { z } from 'zod'

import { Duration, durationMs } from '../duration'

const Match = z.object({ recipient: z.string().optional() }).strict()

const Dose = z.union([
    z.object({ count: z.number().int().min(1) }).strict(),
    z.object({ share: z.number().gt(0).max(1) }).strict(),
])

export const CardFault = z
    .object({
        name: z.literal('ses.reject'),
        params: z.object({ type: z.literal('rejected') }).strict(),
        match: Match.optional(),
        dose: Dose,
        for: Duration.optional(),
    })
    .strict()
export type CardFault = z.infer<typeof CardFault>

export type SesStatusAnswer = { status: number; type: string; message: string }

export type SesAnswer =
    | { kind: 'status'; answer: SesStatusAnswer }
    | { kind: 'drop-connection' }
    | { kind: 'no-answer' }
    | { kind: 'stalled-body' }

export type FaultRule = {
    name: string
    answer: SesAnswer
    match?: z.infer<typeof Match>
    dose: z.infer<typeof Dose>
    for?: string
}

const REJECTED: SesStatusAnswer = { status: 400, type: 'MessageRejected', message: 'Message rejected' }

export function ruleOf(fault: CardFault): FaultRule {
    return { ...fault, answer: { kind: 'status', answer: REJECTED } }
}

type ActiveFault = { id: string; rule: FaultRule; until: number; matched: number; applied: number }

const SHARE_TOLERANCE = 1e-9

function matches(rule: FaultRule, recipients: string[]): boolean {
    return rule.match?.recipient === undefined || recipients.includes(rule.match.recipient)
}

function doseTakes({ rule: { dose }, matched, applied }: ActiveFault): boolean {
    if ('count' in dose) {
        return applied < dose.count
    }
    const crossings = (sends: number): number => Math.floor(sends * dose.share + SHARE_TOLERANCE)
    return crossings(matched) > crossings(matched - 1)
}

export class FaultList {
    private faults: ActiveFault[] = []

    add(rule: FaultRule): string {
        const id = randomUUID()
        const until = rule.for === undefined ? Infinity : Date.now() + durationMs(rule.for)
        this.faults.push({ id, rule, until, matched: 0, applied: 0 })
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

    take(recipients: string[]): FaultRule | undefined {
        const now = Date.now()
        this.faults = this.faults.filter((fault) => fault.until > now)
        for (const fault of this.faults) {
            if (!matches(fault.rule, recipients)) {
                continue
            }
            fault.matched += 1
            if (doseTakes(fault)) {
                fault.applied += 1
                return fault.rule
            }
        }
        return undefined
    }
}
