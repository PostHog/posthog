import { IncomingEvent } from '../../types'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export const SURVEY_EVENTS = {
    SHOWN: 'survey shown',
} as const

export const SURVEY_PERSON_PROPERTIES = {
    LAST_SEEN_DATE: '$survey_last_seen_date',
} as const

export function createEnrichSurveyPersonPropertiesStep<T extends { event: IncomingEvent }>(): ProcessingStep<T, T> {
    return async function enrichSurveyPersonPropertiesStep(input) {
        const { event } = input

        if (event.event.event === SURVEY_EVENTS.SHOWN) {
            event.event.properties = event.event.properties || {}
            event.event.properties['$set'] = event.event.properties['$set'] || {}
            // Only set if not already present (allows explicit $set to override)
            if (!(SURVEY_PERSON_PROPERTIES.LAST_SEEN_DATE in event.event.properties['$set'])) {
                event.event.properties['$set'][SURVEY_PERSON_PROPERTIES.LAST_SEEN_DATE] = event.event.timestamp
            }
        }

        return Promise.resolve(ok(input))
    }
}
