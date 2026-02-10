import { createTestEventHeaders } from '~/tests/helpers/event-headers'

import { PipelineResultType } from '../pipelines/results'
import {
    SURVEY_EVENTS,
    SURVEY_PERSON_PROPERTIES,
    createEnrichSurveyPersonPropertiesStep,
} from './enrich-survey-person-properties'

describe('createEnrichSurveyPersonPropertiesStep', () => {
    const step = createEnrichSurveyPersonPropertiesStep()

    const createEvent = (eventName: string, properties?: Record<string, unknown>, timestamp?: string) => ({
        event: {
            event: eventName,
            distinct_id: 'user123',
            team_id: 1,
            ip: '127.0.0.1',
            site_url: 'https://example.com',
            now: '2021-01-01T00:00:00Z',
            uuid: '123e4567-e89b-12d3-a456-426614174000',
            timestamp: timestamp || '2021-01-01T12:00:00Z',
            properties,
        },
        headers: createTestEventHeaders({
            token: 'token123',
            distinct_id: 'user123',
            timestamp: '2021-01-01T00:00:00Z',
        }),
    })

    it('adds $survey_last_seen_date to $set for survey shown events', async () => {
        const input = createEvent(SURVEY_EVENTS.SHOWN, { $survey_id: 'test-survey' }, '2021-01-01T12:00:00Z')
        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        expect(input.event.properties!['$set']).toEqual({
            [SURVEY_PERSON_PROPERTIES.LAST_SEEN_DATE]: '2021-01-01T12:00:00Z',
        })
    })

    it('preserves existing $set properties and allows them to override', async () => {
        const input = createEvent(
            SURVEY_EVENTS.SHOWN,
            {
                $survey_id: 'test-survey',
                $set: { existing_prop: 'value', [SURVEY_PERSON_PROPERTIES.LAST_SEEN_DATE]: 'custom-override' },
            },
            '2021-01-01T12:00:00Z'
        )
        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        expect(input.event.properties!['$set']).toEqual({
            [SURVEY_PERSON_PROPERTIES.LAST_SEEN_DATE]: 'custom-override',
            existing_prop: 'value',
        })
    })

    it('does not modify non-survey events', async () => {
        const input = createEvent('$pageview', { url: '/home' })
        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        expect(input.event.properties!['$set']).toBeUndefined()
    })

    it('handles survey shown events with no properties', async () => {
        const input = createEvent(SURVEY_EVENTS.SHOWN, undefined, '2021-01-01T12:00:00Z')
        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        expect(input.event.properties!['$set']).toEqual({
            [SURVEY_PERSON_PROPERTIES.LAST_SEEN_DATE]: '2021-01-01T12:00:00Z',
        })
    })
})
