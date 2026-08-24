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
 * committing offsets: a silent stall that otherwise shows only as consumer lag
 * with nothing naming this fork as the cause. Sustained non-zero is that signal.
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
 * Every failure path continues toward the events table; the produce ack rides
 * as a side effect. Must be piped without a retry envelope — a retry would
 * queue the produce again.
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
        try {
            const messages: IngestionOutputMessage[] = []
            for (const { event } of flagCalledEvents) {
                const flagKey = event.properties['$feature_flag']
                if (typeof flagKey !== 'string' || flagKey === '') {
                    // flag_key is materialized into the table's sort key; a row
                    // without it is junk.
                    flagEvaluationsEventsTotal.labels('continued_invalid_flag_key').inc()
                    continue
                }
                if (event.properties['$set'] || event.properties['$set_once']) {
                    // Sizes the person-property loss a dedicated flag lane that
                    // bypasses person processing would cause.
                    flagEvaluationsSetPropsTotal.inc()
                }
                const row = mapProcessedEventToFlagEvaluationRow(event)
                messages.push({ key: row.uuid, value: Buffer.from(JSON.stringify(row)), teamId: row.team_id })
            }
            if (messages.length === 0) {
                return Promise.resolve(ok(input))
            }
            const ack = outputs.queueMessages(FLAG_EVALUATIONS_OUTPUT, messages)
            flagEvaluationsPendingAcks.inc(messages.length)
            // Count on the ack, not the enqueue, so a failed produce is not reported as
            // dual-written. Neither arm runs while the ack is merely pending, which is
            // why the stall needs its own gauge.
            const settled = ack.then(
                () => {
                    flagEvaluationsPendingAcks.dec(messages.length)
                    flagEvaluationsEventsTotal.labels('dual_written').inc(messages.length)
                },
                (error: unknown) => {
                    flagEvaluationsPendingAcks.dec(messages.length)
                    if (error instanceof MessageSizeTooLarge) {
                        // A row over the broker's limit is the same size on redelivery, so
                        // gating the offset commit on it would replay the partition forever.
                        // emit-event skips an oversized event for that reason; drop the
                        // shadow row and let the event continue.
                        flagEvaluationsEventsTotal.labels('continued_message_too_large').inc(messages.length)
                        return
                    }
                    // Transient broker failures stay blocking: this rejection is what
                    // holds the batch's offset commit until the produce lands.
                    flagEvaluationsEventsTotal.labels('produce_failed').inc(messages.length)
                    throw error
                }
            )
            return Promise.resolve(ok(input, [settled]))
        } catch (error) {
            logger.warn('Failed to fork $feature_flag_called event to flag_evaluations, continuing', {
                teamId: input.teamId,
                error,
            })
            flagEvaluationsEventsTotal.labels('continued_fork_error').inc(flagCalledEvents.length)
            return Promise.resolve(ok(input))
        }
    }
}
