import { setTimeout as sleep } from 'timers/promises'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import type { TruthPage, TruthRecord } from '../provider-edge'

export interface SesFeedback {
    settled(unitId: string): Promise<string | undefined>
}

export type SesFeedbackOptions = {
    edgeUrl: string
    lag: () => Promise<number>
    withinMs?: number
    pollMs?: number
}

const FEEDBACK_ANSWERED = 200

export function watchSesFeedback({ edgeUrl, lag, withinMs = 60_000, pollMs = 500 }: SesFeedbackOptions): SesFeedback {
    const answers = new Map<string, Pick<TruthRecord, 'status' | 'detail'>>()
    let cursor = 0
    let reading: Promise<void> | undefined

    const readTruth = async (): Promise<void> => {
        for (;;) {
            const response = await internalFetch(`${edgeUrl}/_truth?after=${cursor}`)
            const text = await response.text()
            if (response.status !== 200) {
                throw new Error(`The edge answered /_truth with ${response.status}: ${text}`)
            }
            const page = parseJSON(text) as TruthPage
            if (page.records.length === 0) {
                return
            }
            for (const { kind, unitId, status, detail } of page.records) {
                if (kind === 'ses.feedback' && unitId !== undefined) {
                    answers.set(unitId, { status, detail })
                }
            }
            cursor = page.next
        }
    }
    const read = (): Promise<void> => (reading ??= readTruth().finally(() => (reading = undefined)))

    return {
        async settled(unitId) {
            const deadline = Date.now() + withinMs
            for (;;) {
                await read()
                const answer = answers.get(unitId)
                if (answer?.status === FEEDBACK_ANSWERED) {
                    break
                }
                if (answer !== undefined) {
                    return `the SES feedback was not taken: ${answer.detail.error ?? `cdp-api answered ${answer.status}`}`
                }
                if (Date.now() >= deadline) {
                    return `the edge recorded no SES feedback within ${withinMs / 1000}s`
                }
                await sleep(pollMs)
            }
            for (;;) {
                const behind = await lag()
                if (behind === 0) {
                    return undefined
                }
                if (Date.now() >= deadline) {
                    return `the SES webhooks consumer was ${behind} messages behind after ${withinMs / 1000}s`
                }
                await sleep(pollMs)
            }
        },
    }
}
