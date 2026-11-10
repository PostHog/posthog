import { randomUUID } from 'crypto'
import { z } from 'zod'

import { Duration, durationMs } from '../duration'

const Match = z.object({ recipient: z.string().optional() }).strict()

const Dose = z.union([
    z.object({ count: z.number().int().min(1) }).strict(),
    z.object({ share: z.number().gt(0).max(1) }).strict(),
])

const SesReject = z
    .object({
        name: z.literal('ses.reject'),
        params: z.object({ type: z.literal('rejected') }).strict(),
    })
    .strict()

const Dosing = { match: Match.optional(), dose: Dose, for: Duration.optional() }

export const CardFault = z.discriminatedUnion('name', [SesReject.extend(Dosing)])
export type CardFault = z.infer<typeof CardFault>

export type SesStatusAnswer = { status: number; type: string; message: string }

type AdapterFault =
    | { name: 'ses.status'; params: SesStatusAnswer }
    | { name: 'ses.drop_connection'; params: Record<string, never> }

export type FaultSpec = (Pick<CardFault, 'name' | 'params'> | AdapterFault) & {
    match?: z.infer<typeof Match>
    dose?: z.infer<typeof Dose>
    for?: string
}

export type SesAnswer = { kind: 'status'; answer: SesStatusAnswer } | { kind: 'drop-connection' }

type ActiveFault = {
    id: string
    spec: FaultSpec
    until: number
    matched: number
    applied: number
}

export type AppliedFault = { name: FaultSpec['name']; answer: SesAnswer }

const REJECTED: SesStatusAnswer = { status: 400, type: 'MessageRejected', message: 'Message rejected' }

function answerOf(spec: FaultSpec): SesAnswer {
    switch (spec.name) {
        case 'ses.reject':
            return { kind: 'status', answer: REJECTED }
        case 'ses.status':
            return { kind: 'status', answer: spec.params }
        case 'ses.drop_connection':
            return { kind: 'drop-connection' }
    }
}

function matches(spec: FaultSpec, recipients: string[]): boolean {
    return spec.match?.recipient === undefined || recipients.includes(spec.match.recipient)
}

function doseTakes(fault: ActiveFault): boolean {
    const dose = fault.spec.dose
    if (dose === undefined) {
        return true
    }
    if ('count' in dose) {
        return fault.applied < dose.count
    }
    return Math.floor(fault.matched * dose.share) > Math.floor((fault.matched - 1) * dose.share)
}

export class FaultList {
    private faults: ActiveFault[] = []

    add(spec: FaultSpec): string {
        const id = randomUUID()
        const until = spec.for === undefined ? Infinity : Date.now() + durationMs(spec.for)
        this.faults.push({ id, spec, until, matched: 0, applied: 0 })
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

    take(recipients: string[]): AppliedFault | undefined {
        const now = Date.now()
        this.faults = this.faults.filter((fault) => fault.until > now)
        for (const fault of this.faults) {
            if (!matches(fault.spec, recipients)) {
                continue
            }
            fault.matched += 1
            if (doseTakes(fault)) {
                fault.applied += 1
                return { name: fault.spec.name, answer: answerOf(fault.spec) }
            }
        }
        return undefined
    }
}
