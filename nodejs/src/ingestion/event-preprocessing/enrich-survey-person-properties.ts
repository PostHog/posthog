import { IncomingEvent } from '../../types'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export const SURVEY_EVENTS = {
    SHOWN: 'survey shown',
} as const

export const SURVEY_PERSON_PROPERTIES = {
    LAST_SEEN_DATE: '$survey_last_seen_date',
} as const

/**
 * Enriches survey events with person properties.
 * When a "survey shown" event is received, adds $survey_last_seen_date to $set
 * so it gets processed as a normal person property update.
 */
export function createEnrichSurveyPersonPropertiesStep<T extends { event: IncomingEvent }>(): ProcessingStep<T, T> {
    return async function enrichSurveyPersonPropertiesStep(input) {
        const { event } = input

        if (event.event.event === SURVEY_EVENTS.SHOWN) {
            event.event.properties = event.event.properties || {}
            event.event.properties['$set'] = {
                [SURVEY_PERSON_PROPERTIES.LAST_SEEN_DATE]: event.event.timestamp,
                ...event.event.properties['$set'],
            }
        }

        return Promise.resolve(ok(input))
    }
}
