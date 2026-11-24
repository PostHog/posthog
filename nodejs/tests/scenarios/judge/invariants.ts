import { isDeepStrictEqual } from 'util'
import { z } from 'zod'

import { RETRIABLE_STATUS_CODES } from '~/cdp/utils/cdp-fetch'

import type { ResidentBacklog, ResidentRows } from '../backlog/backlog'
import type { Definition } from '../cards/definitions'
import type { TruthRecord } from '../provider-edge'
import { addressesOf } from '../provider-edge/ses'
import type { FollowUpAnswer, IntakeAnswer, InvariantResult, JournalEntry } from './judge'

export type JudgeEvidence = {
    journal: readonly JournalEntry[]
    truth: readonly TruthRecord[]
    fetchRetries: number
    resident?: ResidentBacklog
    janitorResets: number
    boundary: RunBoundary
}

export type RunBoundary = {
    truthFrom: number
    horizon?: { seq: number; at: number } | { unread: string }
    unread?: string
    unsettled?: string
    unobserved: readonly string[]
}

export type InvariantDefinition = Definition & {
    check(evidence: JudgeEvidence, gate: number | undefined, params: unknown): Omit<InvariantResult, 'name'>
}

const EVIDENCE_UNIT_IDS = 5

export function crossedByOf(
    journal: readonly JournalEntry[],
    violations: readonly { unitId: string; count?: number }[],
    allowed: number
): string | undefined {
    const offers = new Map(journal.map(({ unitId, offeredAt, step }) => [unitId, { offeredAt, step: step ?? 0 }]))
    const offerOf = (unitId: string): { offeredAt: number; step: number } =>
        offers.get(unitId) ?? { offeredAt: Infinity, step: Infinity }
    const earlier = (a: string, b: string): number =>
        offerOf(a).offeredAt - offerOf(b).offeredAt || offerOf(a).step - offerOf(b).step
    let seen = 0
    for (const { unitId, count = 1 } of [...violations].sort((a, b) => earlier(a.unitId, b.unitId))) {
        seen += count
        if (seen > allowed) {
            return unitId
        }
    }
    return undefined
}

const crossing = (crossedBy: string | undefined): { crossedBy?: string } => (crossedBy ? { crossedBy } : {})

export const deliveryKey = (unitId: string, actionId: string): string => `${unitId}/${actionId}`

const ERROR_TYPES_THE_EMAIL_SERVICE_RETRIES = ['TooManyRequestsException', 'ThrottlingException']

const isAccepted = (status: number): boolean => status >= 200 && status < 300

const isNotRetriedByTheEmailService = ({ status, detail }: TruthRecord): boolean =>
    status >= 400 && status < 500 && !ERROR_TYPES_THE_EMAIL_SERVICE_RETRIES.includes(detail.errorType ?? '')

const isNotRetriedByFetch = (status: number): boolean => !RETRIABLE_STATUS_CODES.includes(status)

function endedByFault(records: TruthRecord[], fetchRetries: number): boolean {
    const last = records.at(-1)
    if (last?.fault === undefined) {
        return false
    }
    if (last.kind !== 'webhook') {
        return isNotRetriedByTheEmailService(last)
    }
    return isNotRetriedByFetch(last.status) || records.length >= fetchRetries
}

type DeliveryRecord = TruthRecord & { unitId: string; actionId: string }

const isDeliveryRecord = (record: TruthRecord): record is DeliveryRecord =>
    record.unitId !== undefined && record.actionId !== undefined

const recordsByDelivery = (truth: readonly TruthRecord[]): Map<string, DeliveryRecord[]> =>
    Map.groupBy(truth.filter(isDeliveryRecord), ({ unitId, actionId }) => deliveryKey(unitId, actionId))

export type DeliveryEvidence = Pick<JudgeEvidence, 'journal' | 'truth' | 'fetchRetries'>

export const missedDeliveriesOf = ({
    journal,
    truth,
    fetchRetries,
}: DeliveryEvidence): { unitId: string; actionId: string; records: DeliveryRecord[] }[] => {
    const byDelivery = recordsByDelivery(truth)
    return journal
        .filter(({ answer }) => answer.accepted)
        .flatMap(({ unitId, expect }) =>
            expect.deliveries.map((actionId) => ({
                unitId,
                actionId,
                records: byDelivery.get(deliveryKey(unitId, actionId)) ?? [],
            }))
        )
        .filter(
            ({ records }) => !records.some(({ status }) => isAccepted(status)) && !endedByFault(records, fetchRetries)
        )
}

export const acceptedDeliveriesOf = (truth: readonly TruthRecord[]): { record: DeliveryRecord; accepted: number }[] =>
    [...recordsByDelivery(truth).values()]
        .map((records) => ({ record: records[0], accepted: records.filter(({ status }) => isAccepted(status)).length }))
        .filter(({ accepted }) => accepted > 0)

export const atLeastOnce: InvariantDefinition = {
    name: 'at_least_once',
    params: z.object({}).strict(),
    check: (evidence) => {
        const missed = missedDeliveriesOf(evidence)
        const [first] = missed
        return {
            passed: missed.length === 0,
            observed: missed.length,
            violation:
                first &&
                `${first.unitId} ${first.actionId}: ${
                    first.records.length === 0
                        ? 'the edge never received it'
                        : `the last of ${first.records.length} attempts was answered ${first.records.at(-1)!.status}`
                }`,
            unitIds: [...new Set(missed.map(({ unitId }) => unitId))].slice(0, EVIDENCE_UNIT_IDS),
            ...crossing(crossedByOf(evidence.journal, missed, 0)),
        }
    },
}

const withinGate = (observed: number, gate: number | undefined): boolean => observed <= (gate ?? 0)

const firstUnitIds = (unitIds: string[]): string[] => [...new Set(unitIds)].slice(0, EVIDENCE_UNIT_IDS)

const plural = (count: number, noun: string): string => `${count} ${noun}${count === 1 ? '' : 's'}`

export const duplicateSends: InvariantDefinition = {
    name: 'duplicate_sends',
    params: z.object({}).strict(),
    check: ({ journal, truth, janitorResets }, gate) => {
        const duplicated = acceptedDeliveriesOf(truth)
            .map(({ record, accepted }) => ({ record, extra: accepted - 1 }))
            .filter(({ extra }) => extra > 0)
        const observed = duplicated.reduce((sum, { extra }) => sum + extra, 0)
        const [first] = duplicated
        const allowed = `${plural(janitorResets, 'job')} the janitor reset${gate ? ` plus a gate of ${gate}` : ''}`
        const why = `${plural(observed, 'duplicate')} against ${allowed}`
        return {
            passed: observed <= janitorResets + (gate ?? 0),
            observed,
            violation:
                first && `${first.record.unitId} ${first.record.actionId}: accepted ${first.extra + 1} times; ${why}`,
            unitIds: firstUnitIds(duplicated.map(({ record }) => record.unitId)),
            ...crossing(
                crossedByOf(
                    journal,
                    duplicated.map(({ record, extra }) => ({ unitId: record.unitId, count: extra })),
                    janitorResets + (gate ?? 0)
                )
            ),
        }
    },
}

type Refusal = JournalEntry & { answer: Extract<IntakeAnswer, { accepted: false }> }

export const refusalsOf = (journal: readonly JournalEntry[]): Refusal[] =>
    journal.flatMap((entry) => (entry.answer.accepted || entry.kind === 'event' ? [] : [entry as Refusal]))

export const refusedAtIntake: InvariantDefinition = {
    name: 'refused_at_intake',
    params: z.object({}).strict(),
    check: ({ journal }, gate) => {
        const refused = refusalsOf(journal)
        const [first] = refused
        const reason = (answer: (typeof refused)[number]['answer']): string =>
            'transportError' in answer
                ? `the intake could not be reached: ${answer.transportError}`
                : `the intake answered ${answer.status}${answer.outcome ? ` ${answer.outcome}` : ''}`
        return {
            passed: withinGate(refused.length, gate),
            observed: refused.length,
            violation: first && `${first.unitId}: ${reason(first.answer)}`,
            unitIds: firstUnitIds(refused.map(({ unitId }) => unitId)),
            ...crossing(crossedByOf(journal, refused, gate ?? 0)),
        }
    },
}

export const residentBacklogIntact: InvariantDefinition = {
    name: 'resident_backlog_intact',
    params: z.object({}).strict(),
    check: ({ resident }) => {
        if (resident?.seeded === undefined) {
            return {
                passed: false,
                observed: 0,
                violation: 'no resident backlog was seeded; run seed-backlog with this profile first',
                unitIds: [],
            }
        }
        const { name, backlog } = resident.profile
        if (resident.seeded.profile !== name) {
            return {
                passed: false,
                observed: 0,
                violation: `the resident backlog was seeded for profile ${resident.seeded.profile}; run seed-backlog with profile ${name} first`,
                unitIds: [],
            }
        }
        if (!isDeepStrictEqual(resident.seeded.backlog, backlog)) {
            return {
                passed: false,
                observed: 0,
                violation: `the resident backlog was seeded from another backlog than profile ${name} holds; run seed-backlog with it again`,
                unitIds: [],
            }
        }
        const keyOf = ({ teamId, queue, status }: ResidentRows): string => `team ${teamId} ${queue} ${status}`
        const seeded = new Map(resident.seeded.rows.map((row) => [keyOf(row), row]))
        const found = new Map(resident.found.map((row) => [keyOf(row), row]))
        const none = { rows: 0, transitions: 0, stateBytes: 0 }
        const changed = [...new Set([...seeded.keys(), ...found.keys()])]
            .sort()
            .map((key) => ({ key, expected: seeded.get(key) ?? none, actual: found.get(key) ?? none }))
            .map(({ key, expected, actual }) => ({
                key,
                expected,
                actual,
                touched: Math.max(
                    Math.abs(expected.rows - actual.rows),
                    Math.abs(expected.transitions - actual.transitions),
                    expected.stateBytes === actual.stateBytes ? 0 : 1
                ),
            }))
            .filter(({ touched }) => touched > 0)
        const [first] = changed
        return {
            passed: changed.length === 0,
            observed: changed.reduce((sum, { touched }) => sum + touched, 0),
            violation: first && residentViolation(first.key, first.expected, first.actual),
            unitIds: [],
        }
    },
}

type ResidentContent = Pick<ResidentRows, 'rows' | 'transitions' | 'stateBytes'>

function residentViolation(key: string, expected: ResidentContent, actual: ResidentContent): string {
    return expected.rows !== actual.rows
        ? `${key}: expected ${expected.rows} rows, found ${actual.rows}`
        : `${key}: the rows changed in place, expected ${expected.transitions} transitions and ${expected.stateBytes} state bytes, found ${actual.transitions} and ${actual.stateBytes}`
}

const SUPPRESSED = { status: 422, outcome: 'recipient_suppressed' }

function unsuppressedReason(followUp: FollowUpAnswer): string | undefined {
    if ('notSent' in followUp) {
        return `the follow-up was not sent: ${followUp.notSent}`
    }
    if (followUp.accepted) {
        return 'cdp-api accepted the follow-up'
    }
    if ('transportError' in followUp) {
        return `cdp-api could not be reached: ${followUp.transportError}`
    }
    return followUp.status === SUPPRESSED.status && followUp.outcome === SUPPRESSED.outcome
        ? undefined
        : `cdp-api answered the follow-up ${followUp.status}${followUp.outcome ? ` ${followUp.outcome}` : ''}`
}

export const bouncedSuppressed: InvariantDefinition = {
    name: 'bounced_suppressed',
    params: z.object({}).strict(),
    check: ({ journal, truth }) => {
        const rejectedSends = truth.filter(
            ({ kind, fault, unitId }) => kind === 'ses.send' && fault === 'ses.reject' && unitId !== undefined
        )
        const bounced = new Set(rejectedSends.filter(({ status }) => isAccepted(status)).map(({ unitId }) => unitId))
        const refusedOutright = new Set(
            rejectedSends.filter(({ status }) => !isAccepted(status)).map(({ unitId }) => unitId)
        )
        const lastBounce = rejectedSends.filter(({ status }) => isAccepted(status)).at(-1)?.seq
        const takenAfterTheFault = new Set(
            truth
                .filter(
                    ({ kind, fault, status, seq }) =>
                        lastBounce !== undefined &&
                        kind === 'ses.send' &&
                        fault === undefined &&
                        isAccepted(status) &&
                        seq > lastBounce
                )
                .map(({ unitId }) => unitId)
        )
        const unsuppressed = journal.flatMap(({ unitId, followUp }) => {
            const skipped =
                followUp !== undefined &&
                'notSent' in followUp &&
                !refusedOutright.has(unitId) &&
                !takenAfterTheFault.has(unitId)
            if (!bounced.has(unitId) && !skipped) {
                return []
            }
            const reason = followUp ? unsuppressedReason(followUp) : 'no follow-up was offered'
            return reason === undefined ? [] : [{ unitId, reason }]
        })
        const [first] = unsuppressed
        return {
            passed: unsuppressed.length === 0,
            observed: unsuppressed.length,
            violation: first && `${first.unitId}: ${first.reason}`,
            unitIds: firstUnitIds(unsuppressed.map(({ unitId }) => unitId)),
        }
    },
}

const runOf = (unitId: string): string => unitId.slice(0, unitId.lastIndexOf('-'))

function unjudgedNoLoss({ journal, truth, boundary }: JudgeEvidence): string | undefined {
    if (boundary.unread !== undefined) {
        return `the truth could not be read: ${boundary.unread}`
    }
    if (boundary.unsettled !== undefined) {
        return boundary.unsettled
    }
    const gap = truth.findIndex(({ seq }, i) => seq !== boundary.truthFrom + i + 1)
    if (gap >= 0) {
        return `the truth skips from seq ${truth[gap - 1]?.seq ?? boundary.truthFrom} to ${truth[gap].seq}`
    }
    if (boundary.unobserved.length > 0) {
        return boundary.unobserved.join('; ')
    }
    const journaled = new Set(journal.map(({ unitId }) => unitId))
    const runs = new Set(journal.map(({ unitId }) => runOf(unitId)))
    const stray = truth
        .filter(isDeliveryRecord)
        .find(({ unitId, status }) => isAccepted(status) && !journaled.has(unitId) && runs.has(runOf(unitId)))
    return (
        stray &&
        `the journal is incomplete: the edge accepted ${stray.unitId} ${stray.actionId}, which the journal never recorded`
    )
}

const unjudgedOf = (unjudged: string): Omit<InvariantResult, 'name'> => ({
    passed: false,
    observed: 0,
    unitIds: [],
    unjudged,
})

type Bounds = { min: number; max: number }

const NONE: Bounds = { min: 0, max: 0 }

function boundsOf({ answer, followUp, expect }: JournalEntry, actionId: string, horizonAt: number): Bounds {
    if (!expect.deliveries.includes(actionId) || (expect.dueAt ?? -Infinity) > horizonAt) {
        return NONE
    }
    if (!answer.accepted) {
        return 'transportError' in answer ? { min: 0, max: 1 } : NONE
    }
    const flows = followUp !== undefined && 'accepted' in followUp && followUp.accepted ? 2 : 1
    return { min: flows, max: flows }
}

type Effect = { recipient: string; flowId?: string }

const effectsOf = ({ kind, detail, flowId }: DeliveryRecord): Effect[] =>
    (kind === 'webhook'
        ? [detail.request?.host ?? '']
        : addressesOf([...(detail.message?.to ?? []), ...(detail.message?.cc ?? []), ...(detail.message?.bcc ?? [])])
    ).map((recipient) => ({ recipient, flowId }))

type Shortfall = { unitId: string; actionId: string; recipient?: string; flows: number; expected: number }

type Excess = {
    unitId: string
    actionId: string
    recipient: string
    flowId?: string
    accepted: number
    expected: number
    excess: number
}

const shortfallOf = ({ unitId, actionId, recipient, flows, expected }: Shortfall): string =>
    `${unitId} ${actionId}${recipient === undefined ? '' : ` to ${recipient}`}: accepted ${expected > 1 ? `from ${plural(flows, 'flow')}` : plural(flows, 'time')} by the recovery horizon, expected ${expected}`

const excessOf = ({ unitId, actionId, recipient, flowId, accepted, expected }: Excess): string =>
    `${unitId} ${actionId} to ${recipient}${flowId === undefined ? '' : ` from ${flowId}`}: accepted ${plural(accepted, 'time')}, expected ${expected}`

export const noLoss: InvariantDefinition = {
    name: 'no_loss',
    params: z.object({}).strict(),
    check: (evidence) => {
        const { horizon } = evidence.boundary
        if (horizon === undefined) {
            return unjudgedOf('the run reached no recovery horizon: convergence was interrupted')
        }
        if ('unread' in horizon) {
            return unjudgedOf(
                `the run reached no recovery horizon: the last convergence read failed: ${horizon.unread}`
            )
        }
        const unjudged = unjudgedNoLoss(evidence)
        if (unjudged !== undefined) {
            return unjudgedOf(unjudged)
        }
        const byDelivery = recordsByDelivery(evidence.truth)
        const actionsByUnit = Map.groupBy(evidence.truth.filter(isDeliveryRecord), ({ unitId }) => unitId)
        const missing: Shortfall[] = []
        const extra: Excess[] = []
        for (const entry of evidence.journal) {
            const { unitId } = entry
            const seen = (actionsByUnit.get(unitId) ?? []).map(({ actionId }) => actionId)
            for (const actionId of new Set([...entry.expect.deliveries, ...seen])) {
                const records = byDelivery.get(deliveryKey(unitId, actionId)) ?? []
                const { min, max } = boundsOf(entry, actionId, horizon.at)
                const accepted = records.filter(({ status }) => isAccepted(status))
                const byRecipient = Map.groupBy(accepted.flatMap(effectsOf), ({ recipient }) => recipient)
                const dueByRecipient = Map.groupBy(
                    accepted.filter(({ seq }) => seq <= horizon.seq).flatMap(effectsOf),
                    ({ recipient }) => recipient
                )
                if (dueByRecipient.size === 0 && min > 0) {
                    missing.push({ unitId, actionId, flows: 0, expected: min })
                }
                for (const [recipient, sends] of dueByRecipient) {
                    const flows = new Set(sends.map(({ flowId }, i) => flowId ?? i)).size
                    if (flows < min) {
                        missing.push({ unitId, actionId, recipient, flows, expected: min })
                    }
                }
                for (const [recipient, sends] of byRecipient) {
                    const byFlow = [...Map.groupBy(sends, ({ flowId }, i) => flowId ?? i)]
                    const repeats = byFlow.reduce((sum, [, { length }]) => sum + length - 1, 0)
                    const excess = repeats + Math.max(0, byFlow.length - max)
                    const resent = byFlow.find(([flowId, { length }]) => typeof flowId === 'string' && length > 1)
                    if (excess > 0) {
                        extra.push({
                            unitId,
                            actionId,
                            recipient,
                            excess,
                            ...(resent
                                ? { flowId: String(resent[0]), accepted: resent[1].length, expected: 1 }
                                : { accepted: sends.length, expected: max }),
                        })
                    }
                }
            }
        }
        const observed =
            missing.reduce((sum, { flows, expected }) => sum + expected - flows, 0) +
            extra.reduce((sum, { excess }) => sum + excess, 0)
        const [lost] = missing
        const [resent] = extra
        const violation = [lost && shortfallOf(lost), resent && excessOf(resent)].filter(Boolean).join('; ')
        return {
            passed: observed === 0,
            observed,
            violation: violation || undefined,
            unitIds: firstUnitIds([...missing, ...extra].map(({ unitId }) => unitId)),
            missing: firstUnitIds(missing.map(({ unitId }) => unitId)),
            extra: firstUnitIds(extra.map(({ unitId }) => unitId)),
        }
    },
}

export const INVARIANTS: InvariantDefinition[] = [
    atLeastOnce,
    duplicateSends,
    refusedAtIntake,
    bouncedSuppressed,
    residentBacklogIntact,
    noLoss,
]
