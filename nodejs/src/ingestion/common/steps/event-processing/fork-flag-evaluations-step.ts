import { Counter, Gauge } from 'prom-client'

import { FLAG_EVALUATIONS_OUTPUT, FlagEvaluationsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { IngestionOutputMessage } from '~/common/outputs/types'
import { MessageSizeTooLarge } from '~/common/utils/db/error'
import { logger } from '~/common/utils/logger'
import { mapProcessedEventToFlagEvaluationRow } from '~/ingestion/common/flag-evaluations/flag-evaluation-row'
import { FlagEvaluationsService } from '~/ingestion/common/flag-evaluations/flag-evaluations-service'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { EventToEmit } from './emit-event-step'

export const flagEvaluationsEventsTotal = new Counter({
    name: 'ingestion_flag_evaluations_events_total',
    help: '$feature_flag_called events seen by the flag-evaluations fork, by outcome',
    labelNames: ['outcome'],
})

/**
 * Produces queued but not yet acknowledged. The ack rides in the batch's side
 * effects, so an unwritable topic leaves it pending and the consumer stops
 * committing offsets. Neither ack arm has run at that point, so no outcome
 * counter moves and this gauge is the only thing that names the fork as the
 * cause.
 *
 * Once the wait passes CONSUMER_BACKGROUND_TASK_TIMEOUT_MS, v1 logs a timeout
 * warning and keeps waiting, and v2 fails the batch with
 * background_task_timeout_after_<ms>ms. Neither one names the fork.
 */
export const flagEvaluationsPendingAcks = new Gauge({
    name: 'ingestion_flag_evaluations_pending_acks',
    help: 'flag_evaluations produces queued but not yet acknowledged; sustained non-zero means the fork is holding up batches',
})

export const flagEvaluationsSetPropsTotal = new Counter({
    name: 'ingestion_flag_evaluations_set_props_total',
    help: '$feature_flag_called events carrying $set/$set_once, which a dedicated flag lane bypassing person processing would lose',
})

const FEATURE_FLAG_CALLED_EVENT = '$feature_flag_called'

const isFlagCalledEvent = ({ event }: EventToEmit<string>): boolean => event.event === FEATURE_FLAG_CALLED_EVENT

// flag_key is materialized into the table's sort key, so a row without it is junk.
const hasFlagKey = ({ event }: EventToEmit<string>): boolean => {
    const flagKey = event.properties['$feature_flag']
    return typeof flagKey === 'string' && flagKey !== ''
}

export interface ForkFlagEvaluationsStepInput {
    eventsToEmit: EventToEmit<string>[]
    teamId: number
}

/**
 * Forks $feature_flag_called events into the flag_evaluations ClickHouse table:
 * narrows the assembled events row to the flag_evaluations column set and
 * produces it to the clickhouse_flag_evaluations topic while the event
 * continues to the events table unchanged.
 *
 * Sits between create-event and emit-event, where the fully assembled
 * ProcessedEvent exists: person_id and person_properties from person
 * processing, and final properties (including the $group_N keys the groups
 * step resolves, which the storage table materializes). Matching on the event
 * name excludes the $experiment_exposure duplicate that create-event appends
 * for allowlisted teams.
 *
 * Every failure path continues toward the events table, including a produce
 * that fails permanently: the row is counted and dropped, never retried. The ack
 * rides as a side effect, so the batch does not commit its offsets until the
 * broker answers. Pipe this step without a retry envelope, because a retry
 * would queue the produce again.
 */
export function createForkFlagEvaluationsStep<T extends ForkFlagEvaluationsStepInput>(
    outputs: IngestionOutputs<FlagEvaluationsOutput>,
    flagEvaluationsService: FlagEvaluationsService
): ProcessingStep<T, T> {
    return function forkFlagEvaluationsStep(input) {
        const flagCalledEvents = input.eventsToEmit.filter(isFlagCalledEvent)
        if (flagCalledEvents.length === 0) {
            return Promise.resolve(ok(input))
        }
        if (!flagEvaluationsService.isEnabledForTeam(input.teamId)) {
            flagEvaluationsEventsTotal.labels('continued_team_not_enabled').inc(flagCalledEvents.length)
            return Promise.resolve(ok(input))
        }
        const mappableEvents = flagCalledEvents.filter(hasFlagKey)
        const invalidFlagKeys = flagCalledEvents.length - mappableEvents.length
        if (invalidFlagKeys > 0) {
            flagEvaluationsEventsTotal.labels('continued_invalid_flag_key').inc(invalidFlagKeys)
        }
        if (mappableEvents.length === 0) {
            return Promise.resolve(ok(input))
        }
        try {
            const messages: IngestionOutputMessage[] = mappableEvents.map(({ event }) => {
                if (event.properties['$set'] || event.properties['$set_once']) {
                    // Sizes the person-property loss a dedicated flag lane that
                    // bypasses person processing would cause.
                    flagEvaluationsSetPropsTotal.inc()
                }
                const row = mapProcessedEventToFlagEvaluationRow(event)
                return { key: row.uuid, value: Buffer.from(JSON.stringify(row)), teamId: row.team_id }
            })
            const ack = outputs.queueMessages(FLAG_EVALUATIONS_OUTPUT, messages)
            flagEvaluationsPendingAcks.inc(messages.length)
            // Count on the ack, not the enqueue, so a failed produce is not reported as
            // dual-written.
            //
            // The ack never rejects. Only one host redelivers the batch on a rejected
            // side effect; the rest stop the process or the pod (see
            // PipelineContext.sideEffects). The backfill owns history for this table,
            // so a lost row costs less than a stopped consumer.
            const settled = ack.then(
                () => {
                    flagEvaluationsPendingAcks.dec(messages.length)
                    flagEvaluationsEventsTotal.labels('dual_written').inc(messages.length)
                },
                (error: unknown) => {
                    flagEvaluationsPendingAcks.dec(messages.length)
                    if (error instanceof MessageSizeTooLarge) {
                        // An oversized row is a property of the row, not of the broker, so
                        // it gets its own outcome and no warning: retrying or alerting on
                        // it would change nothing. emit-event skips an oversized event for
                        // the same reason.
                        flagEvaluationsEventsTotal.labels('continued_message_too_large').inc(messages.length)
                        return
                    }
                    flagEvaluationsEventsTotal.labels('produce_failed').inc(messages.length)
                }
            )
            return Promise.resolve(ok(input, [settled]))
        } catch (error) {
            logger.warn('Failed to fork $feature_flag_called event to flag_evaluations, continuing', {
                teamId: input.teamId,
                error,
            })
            flagEvaluationsEventsTotal.labels('continued_fork_error').inc(mappableEvents.length)
            return Promise.resolve(ok(input))
        }
    }
}
