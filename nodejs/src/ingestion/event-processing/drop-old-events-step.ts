import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { parseEventTimestamp } from '../../worker/ingestion/timestamps'
import { PipelineWarning } from '../pipelines/pipeline.interface'
import { PipelineResult, drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { EventPipelineRunnerInput } from './event-pipeline-runner-v1-step'

/**
 * Creates a pipeline step that drops events older than a team's configured threshold.
 *
 * If an event is too old, it returns a `drop` result with an ingestion warning
 * that will be sent to Kafka by `handleIngestionWarnings`.
 */
export function createDropOldEventsStep(): ProcessingStep<EventPipelineRunnerInput, EventPipelineRunnerInput> {
    return function dropOldEventsStep(
        input: EventPipelineRunnerInput
    ): Promise<PipelineResult<EventPipelineRunnerInput>> {
        const { event, team } = input

        // If no drop threshold is set (null) or set to 0, don't drop any events
        // Zero threshold is ignored to protect from misconfiguration bugs
        if (!team.drop_events_older_than_seconds) {
            return Promise.resolve(ok(input))
        }

        // Convert PipelineEvent to PluginEvent for timestamp parsing
        const pluginEvent: PluginEvent = {
            ...event,
            team_id: team.id,
        }

        const eventTimestamp = parseEventTimestamp(pluginEvent)
        const now = DateTime.fromISO(pluginEvent.now)
        const ageInSeconds = now.diff(eventTimestamp, 'seconds').seconds

        // If the event is older than the threshold, drop it with a warning
        if (ageInSeconds > team.drop_events_older_than_seconds) {
            const warning: PipelineWarning = {
                type: 'event_dropped_too_old',
                details: {
                    eventUuid: pluginEvent.uuid,
                    event: pluginEvent.event,
                    distinctId: pluginEvent.distinct_id,
                    eventTimestamp: eventTimestamp.toISO(),
                    ageInSeconds: Math.floor(ageInSeconds),
                    dropThresholdSeconds: team.drop_events_older_than_seconds,
                },
                alwaysSend: false,
            }
            return Promise.resolve(drop('event_too_old', [], [warning]))
        }

        return Promise.resolve(ok(input))
    }
}
