import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PipelineEvent } from '~/types'

export const SURVEY_EVENTS = {
    SHOWN: 'survey shown',
} as const

export const SURVEY_PERSON_PROPERTIES = {
    LAST_SEEN_DATE: '$survey_last_seen_date',
} as const

export function createEnrichSurveyPersonPropertiesStep<T extends { event: PipelineEvent }>(): ProcessingStep<T, T> {
    return async function enrichSurveyPersonPropertiesStep(input) {
        const { event } = input

        if (event.event === SURVEY_EVENTS.SHOWN) {
            event.properties = event.properties || {}
            event.properties['$set'] = event.properties['$set'] || {}
            // Only set if not already present (allows explicit $set to override)
            if (!(SURVEY_PERSON_PROPERTIES.LAST_SEEN_DATE in event.properties['$set'])) {
                event.properties['$set'][SURVEY_PERSON_PROPERTIES.LAST_SEEN_DATE] = event.timestamp
            }
        }

        return Promise.resolve(ok(input))
    }
}
