
import { sanitizeEventName } from '~/common/utils/db/utils'
import { IngestionWarningType } from '~/ingestion/common/ingestion-warnings'
import {
    featureFlagCalledPropertyCountHistogram,
    invalidTimestampCounter,
} from '~/ingestion/common/metrics'
import { parseEventTimestamp } from '~/ingestion/common/timestamps'
import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, ISOTimestamp, PreIngestionEvent, Team, ValueMatcher } from '~/types'

import {
    FEATURE_FLAG_CALLED_EVENT,
    stripBloatProperties,
    stripFeatureFlagCalledProperties,
} from './strip-bloat-properties'

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

export function createPrepareEventStep<TInput extends PrepareEventStepInput>(
    // Teams opted out of `$feature_flag_called` property stripping. Built once at
    // startup via buildIntegerMatcher; `*` disables stripping globally. Defaults
    // to no exclusions so every team is stripped.
    stripFeatureFlagCalledExcludedTeams: ValueMatcher<number> = () => false
): ProcessingStep<TInput, PrepareEventStepResult<TInput>> {
    return function prepareEventStep(input: TInput) {
        const { normalizedEvent, ...rest } = input

        const warnings: PipelineWarning[] = []
        const invalidTimestampCallback = function (type: IngestionWarningType, details: Record<string, any>) {
            invalidTimestampCounter.labels(type).inc()
            warnings.push({ type, details })
        }

        const properties = normalizedEvent.properties!
        const sanitizedEventName = sanitizeEventName(normalizedEvent['event'])

        if (properties['$ip'] && input.team.anonymize_ips) {
            delete properties['$ip']
        }

        stripBloatProperties(properties)

        if (sanitizedEventName === FEATURE_FLAG_CALLED_EVENT) {
            const propertyCount = stripFeatureFlagCalledExcludedTeams(input.team.id)
                ? Object.keys(properties).length
                : stripFeatureFlagCalledProperties(properties)
            featureFlagCalledPropertyCountHistogram.observe(propertyCount)
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
