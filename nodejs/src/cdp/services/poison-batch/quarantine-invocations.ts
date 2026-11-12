import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'
import { uncompress } from 'snappy'

import { parseKafkaHeaders } from '~/common/kafka/consumer'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { CyclotronJobInvocation, DEAD_LETTER_QUEUE } from '../../types'
import { HogInvocationResultsService } from '../monitoring/hog-invocation-results.service'

const invocationsQuarantined = new Counter({
    name: 'cdp_invocations_quarantined_total',
    help: 'Invocations the dead letter worker gave up on because they crashed it too often. recorded wrote a terminal failure row. unrecorded skipped the invocation without a row, because invocation results are off or the invocation names no team, function or id. failed could not write the row, so the batch fails and is retried.',
    labelNames: ['outcome'],
})

export const QUARANTINED_ERROR_KIND = 'quarantined_after_crashes'

const QUARANTINED_FAILURE = {
    errorKind: QUARANTINED_ERROR_KIND,
    error: 'Processing this invocation failed repeatedly, so it was skipped.',
}

// The message crashed the worker, so the invocation may be partial: fields its payload lacked come from the
// message key and headers.
export type QuarantinedInvocation = { invocation: CyclotronJobInvocation; partition: number; offset: number }

export type TerminalOutcome = 'recorded' | 'unrecorded' | 'failed'

/**
 * Writes the terminal failure row of an invocation the dead letter worker gives up on. failed means no row was
 * written and the caller must not commit past the invocation.
 */
export async function recordTerminal(
    rows: HogInvocationResultsService,
    invocation: CyclotronJobInvocation,
    failure: { errorKind: string; error: string }
): Promise<TerminalOutcome> {
    // A results row needs a team, a function and an id. The message key and headers can lack them, and then the
    // invocation is only logged, because a throw would crash-loop the worker.
    if (
        !Number.isInteger(invocation.teamId) ||
        invocation.teamId <= 0 ||
        invocation.functionId === '' ||
        invocation.id === ''
    ) {
        return 'unrecorded'
    }
    // A function stub makes the row keep the globals, so the invocation can be rerun once the cause is fixed.
    const withGlobals = invocation.state?.globals
        ? { ...invocation, hogFunction: { id: invocation.functionId } }
        : invocation
    let record = await rows.recordTerminalFailure(withGlobals as CyclotronJobInvocation, failure)
    // The payload crashed the worker and can break the row too, so a row without the payload is the fallback.
    // A transient produce failure gets no fallback: the batch fails, and the retry writes the row with the payload.
    if (record === 'unbuildable') {
        record = await rows.recordTerminalFailure({ ...invocation, state: null }, failure)
    }
    if (record === 'disabled') {
        return 'unrecorded'
    }
    return record === 'recorded' ? 'recorded' : 'failed'
}

/**
 * The crash guard's set aside for the dead letter worker. The dead letter worker reads one message per batch, so
 * a flagged batch is the exact message at fault. Instead of running it again, the quarantine records the
 * invocation as a terminal failure and lets the worker commit past it.
 */
export class InvocationQuarantine {
    constructor(
        private workerName: string,
        private rows: HogInvocationResultsService
    ) {}

    public async setAside(messages: Message[]): Promise<void> {
        await this.quarantine(
            await Promise.all(
                messages.map(async (message) => ({
                    invocation: await parseQuarantinedInvocation(message),
                    partition: message.partition,
                    offset: message.offset,
                }))
            )
        )
    }

    /**
     * Records each invocation the dead letter queue gives up on as a terminal failure. The queue commits past
     * the messages once this returns, so it throws when a row could not be written.
     */
    public async quarantine(quarantined: QuarantinedInvocation[]): Promise<void> {
        const outcomes = await Promise.all(
            quarantined.map(({ invocation }) => recordTerminal(this.rows, invocation, QUARANTINED_FAILURE))
        )

        quarantined.forEach(({ invocation, partition, offset }, i) => {
            invocationsQuarantined.labels(outcomes[i]).inc()
            if (outcomes[i] === 'failed') {
                return
            }
            logger.error('☠️', `${this.workerName} - quarantined an invocation that crashed the worker repeatedly`, {
                functionId: invocation.functionId,
                teamId: invocation.teamId,
                invocationId: invocation.id,
                partition,
                offset,
                errorKind: QUARANTINED_ERROR_KIND,
                recorded: outcomes[i] === 'recorded',
            })
        })
        if (outcomes.includes('failed')) {
            throw new Error('Could not record the terminal failure of a quarantined invocation')
        }
    }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null && !Array.isArray(value)

const CLICKHOUSE_DATETIME = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d{1,6})?$/

// The results service writes firstScheduledAt into first_scheduled_at verbatim, and ClickHouse skips a row whose
// value it cannot parse. Without the field, the row falls back to scheduled_at like any other writer's row.
const withReadableFirstScheduledAt = (state: Record<string, unknown>): Record<string, unknown> => {
    const { firstScheduledAt, ...rest } = state
    if (firstScheduledAt === undefined) {
        return state
    }
    const readable =
        typeof firstScheduledAt === 'string' &&
        CLICKHOUSE_DATETIME.test(firstScheduledAt) &&
        // A day past the end of its month passes the pattern, and Date rolls it over to the next month.
        new Date(`${firstScheduledAt.slice(0, 19).replace(' ', 'T')}Z`).toISOString().slice(0, 19) ===
            firstScheduledAt.slice(0, 19).replace(' ', 'T')
    return readable ? state : rest
}

/**
 * Reads a message that crashed the worker without throwing, because a throw here would crash the worker on
 * the same message again. A payload that does not parse keeps the invocation id, team and function from the
 * key and the headers every cyclotron producer sets.
 */
export async function parseQuarantinedInvocation(message: Message): Promise<CyclotronJobInvocation> {
    const headers = parseKafkaHeaders(message.headers)
    let payload: unknown = null
    if (message.value) {
        const raw = message.value
        const value = await uncompress(raw).catch(() => raw)
        try {
            payload = parseJSON(value.toString())
        } catch {
            payload = null
        }
    }
    const body = isRecord(payload) ? payload : {}
    // queueScheduledAt is left out, because JSON turns it into a string and the results row needs a DateTime.
    return {
        id: typeof body.id === 'string' ? body.id : (message.key?.toString() ?? ''),
        teamId: typeof body.teamId === 'number' ? body.teamId : Number(headers.teamId),
        functionId: typeof body.functionId === 'string' ? body.functionId : (headers.functionId ?? ''),
        parentRunId: typeof body.parentRunId === 'string' ? body.parentRunId : undefined,
        state: isRecord(body.state) ? withReadableFirstScheduledAt(body.state) : null,
        queue: DEAD_LETTER_QUEUE,
        queuePriority: typeof body.queuePriority === 'number' ? body.queuePriority : 0,
        queueSource: 'kafka',
    }
}
