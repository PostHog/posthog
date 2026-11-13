import { z } from 'zod'

import { RETRIABLE_STATUS_CODES } from '~/cdp/utils/cdp-fetch'

import type { Definition } from '../cards/definitions'
import type { TruthRecord } from '../provider-edge'
import type { InvariantResult, JournalEntry } from './judge'

export type JudgeEvidence = { journal: readonly JournalEntry[]; truth: readonly TruthRecord[] }

export type InvariantDefinition = Definition & {
    check(evidence: JudgeEvidence, gate: number | undefined): Omit<InvariantResult, 'name'>
}

const EVIDENCE_UNIT_IDS = 5

export const deliveryKey = (unitId: string, actionId: string): string => `${unitId}/${actionId}`

const ERROR_TYPES_THE_EMAIL_SERVICE_RETRIES = ['TooManyRequestsException', 'ThrottlingException']

const isAccepted = (status: number): boolean => status >= 200 && status < 300

const isNotRetriedByTheEmailService = ({ status, detail }: TruthRecord): boolean =>
    status >= 400 && status < 500 && !ERROR_TYPES_THE_EMAIL_SERVICE_RETRIES.includes(detail.errorType ?? '')

const isNotRetriedByFetch = (status: number): boolean => !RETRIABLE_STATUS_CODES.includes(status)

function endedByTerminalFault(records: TruthRecord[]): boolean {
    const last = records.at(-1)
    if (last?.fault === undefined) {
        return false
    }
    return last.kind === 'webhook' ? isNotRetriedByFetch(last.status) : isNotRetriedByTheEmailService(last)
}

type DeliveryRecord = TruthRecord & { unitId: string; actionId: string }

const isDeliveryRecord = (record: TruthRecord): record is DeliveryRecord =>
    record.unitId !== undefined && record.actionId !== undefined

const recordsByDelivery = (truth: readonly TruthRecord[]): Map<string, TruthRecord[]> =>
    Map.groupBy(truth.filter(isDeliveryRecord), ({ unitId, actionId }) => deliveryKey(unitId, actionId))

export const atLeastOnce: InvariantDefinition = {
    name: 'at_least_once',
    params: z.object({}).strict(),
    check: ({ journal, truth }) => {
        const byDelivery = recordsByDelivery(truth)
        const missed = journal
            .filter(({ answer }) => answer.accepted)
            .flatMap(({ unitId, expect }) =>
                expect.deliveries.map((actionId) => ({
                    unitId,
                    actionId,
                    records: byDelivery.get(deliveryKey(unitId, actionId)) ?? [],
                }))
            )
            .filter(
                ({ records }) => !records.some(({ status }) => isAccepted(status)) && !endedByTerminalFault(records)
            )
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
        }
    },
}

export const INVARIANTS: InvariantDefinition[] = [atLeastOnce]
