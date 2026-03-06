import { PluginEvent } from '~/plugin-scaffold'

import { EventHeaders, ISOTimestamp, PreIngestionEvent, Team } from '../../types'
import { sanitizeEventName } from '../../utils/db/utils'
import { invalidTimestampCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { parseEventTimestamp } from '../../worker/ingestion/timestamps'
import { PipelineWarning } from '../pipelines/pipeline.interface'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export type PrepareEventStepInput = {
    normalizedEvent: PluginEvent
    team: Team
    processPerson: boolean
    headers: EventHeaders
}

export type PrepareEventStepResult<TInput> = Omit<TInput, 'normalizedEvent'> & {
    preparedEvent: PreIngestionEvent
    historicalMigration: boolean
}

export function createPrepareEventStep<TInput extends PrepareEventStepInput>(): ProcessingStep<
    TInput,
    PrepareEventStepResult<TInput>
> {
    return function prepareEventStep(input: TInput) {
        const { normalizedEvent, ...rest } = input

        const warnings: PipelineWarning[] = []
        const invalidTimestampCallback = function (type: string, details: Record<string, any>) {
            invalidTimestampCounter.labels(type).inc()
            warnings.push({ type, details })
        }

        const properties = normalizedEvent.properties!
        const sanitizedEventName = sanitizeEventName(normalizedEvent['event'])

        if (properties['$ip'] && input.team.anonymize_ips) {
            delete properties['$ip']
        }

        const timestamp = parseEventTimestamp(normalizedEvent, invalidTimestampCallback)

        const preparedEvent: PreIngestionEvent = {
            eventUuid: normalizedEvent.uuid,
            event: sanitizedEventName,
            distinctId: String(normalizedEvent.distinct_id),
            properties,
            timestamp: timestamp.toISO() as ISOTimestamp,
            teamId: input.team.id,
            projectId: input.team.project_id,
        }

        const historicalMigration = input.headers.historical_migration ?? false

        return Promise.resolve(
            ok(
                {
                    ...rest,
                    preparedEvent,
                    historicalMigration,
                },
                [],
                warnings
            )
        )
    }
}
