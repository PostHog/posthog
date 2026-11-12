import { setTimeout as sleep } from 'timers/promises'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import type { TruthHead, TruthPage, TruthRecord } from '../provider-edge'

export interface SesFeedback {
    settled(unitId: string, signal: AbortSignal): Promise<string | undefined>
}

export type SesFeedbackOptions = {
    edgeUrl: string
    lag: () => Promise<number>
    withinMs?: number
    pollMs?: number
}

const FEEDBACK_ANSWERED = 200

async function truthHead(edgeUrl: string): Promise<number> {
    const response = await internalFetch(`${edgeUrl}/_truth/head`)
    const text = await response.text()
    if (response.status !== 200) {
        throw new Error(`The edge answered /_truth/head with ${response.status}: ${text}`)
    }
    return (parseJSON(text) as TruthHead).head
}

export async function watchSesFeedback({
    edgeUrl,
    lag,
    withinMs = 60_000,
    pollMs = 500,
}: SesFeedbackOptions): Promise<SesFeedback> {
    const answers = new Map<string, Pick<TruthRecord, 'status' | 'detail'>>()
    let cursor = await truthHead(edgeUrl)
    let reading: Promise<boolean> | undefined
    let readsDone = 0

    const readTruthPage = async (): Promise<boolean> => {
        const response = await internalFetch(`${edgeUrl}/_truth?after=${cursor}`)
        const text = await response.text()
        if (response.status !== 200) {
            throw new Error(`The edge answered /_truth with ${response.status}: ${text}`)
        }
        const page = parseJSON(text) as TruthPage
        for (const { kind, unitId, status, detail } of page.records) {
            if (kind === 'ses.feedback' && unitId !== undefined) {
                answers.set(unitId, { status, detail })
            }
        }
        cursor = page.next
        readsDone += 1
        return page.records.length > 0
    }
    const read = (): Promise<boolean> => (reading ??= readTruthPage().finally(() => (reading = undefined)))

    type LagProbe = { afterReads: number; behind: Promise<number>; settledAt?: number }
    let lagProbe: LagProbe | undefined
    const isFresh = (probe: LagProbe, seenAfterReads: number): boolean =>
        probe.afterReads >= seenAfterReads && (probe.settledAt === undefined || Date.now() - probe.settledAt < pollMs)
    const probeLag = (seenAfterReads: number): Promise<number> => {
        if (lagProbe === undefined || !isFresh(lagProbe, seenAfterReads)) {
            const probe: LagProbe = {
                afterReads: readsDone,
                behind: lag().finally(() => (probe.settledAt = Date.now())),
            }
            lagProbe = probe
        }
        return lagProbe.behind
    }

    return {
        async settled(unitId, signal) {
            const deadline = Date.now() + withinMs
            let seenAfterReads = 0
            for (;;) {
                const morePages = await read()
                const answer = answers.get(unitId)
                if (answer?.status === FEEDBACK_ANSWERED) {
                    seenAfterReads = readsDone
                    break
                }
                if (answer !== undefined) {
                    return `the SES feedback was not taken: ${answer.detail.error ?? `cdp-api answered ${answer.status}`}`
                }
                if (Date.now() >= deadline) {
                    return `the edge recorded no SES feedback within ${withinMs / 1000}s`
                }
                await sleep(morePages ? 0 : pollMs, undefined, { signal })
            }
            for (;;) {
                const behind = await probeLag(seenAfterReads)
                if (behind === 0) {
                    return undefined
                }
                if (Date.now() >= deadline) {
                    return `the SES webhooks consumer was ${behind} messages behind after ${withinMs / 1000}s`
                }
                await sleep(pollMs, undefined, { signal })
            }
        },
    }
}
