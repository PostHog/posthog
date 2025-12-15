import { PluginEvent } from '@posthog/plugin-scaffold'

import { InternalEventHandlerContext } from '../../registry'
import { surveyShownHandler } from './surveyShown'

const buildSurveyEvent = (overrides?: Partial<PluginEvent>): PluginEvent => {
    return {
        event: 'survey shown',
        distinct_id: 'user-123',
        team_id: 1,
        timestamp: '2024-01-15T10:00:00Z',
        properties: {},
        ip: null,
        site_url: '',
        now: '',
        uuid: '',
        ...overrides,
    }
}

const emptyContext: InternalEventHandlerContext = {}

describe('surveysHandler', () => {
    it('should set $last_seen_survey_date on survey shown events', async () => {
        const event = buildSurveyEvent()

        await surveyShownHandler.handle(event, emptyContext)

        expect(event.properties!['$set']).toEqual({
            $last_seen_survey_date: '2024-01-15T10:00:00Z',
        })
    })

    it('should use current date if no timestamp on event', async () => {
        const event = buildSurveyEvent({ timestamp: undefined })

        const before = new Date().toISOString()
        await surveyShownHandler.handle(event, emptyContext)
        const after = new Date().toISOString()

        const setDate = event.properties!['$set']['$last_seen_survey_date'] as string
        expect(setDate >= before).toBe(true)
        expect(setDate <= after).toBe(true)
    })

    it('should preserve existing $set properties', async () => {
        const event = buildSurveyEvent({ properties: { $set: { existing_prop: 'value' } } })

        await surveyShownHandler.handle(event, emptyContext)

        expect(event.properties!['$set']).toEqual({
            existing_prop: 'value',
            $last_seen_survey_date: '2024-01-15T10:00:00Z',
        })
    })

    it('should create properties object if missing', async () => {
        const event = buildSurveyEvent({ properties: undefined })

        await surveyShownHandler.handle(event, emptyContext)

        expect(event.properties!['$set']).toEqual({
            $last_seen_survey_date: '2024-01-15T10:00:00Z',
        })
    })

    it('should be registered for survey shown event', () => {
        expect(surveyShownHandler.events).toEqual(['survey shown'])
    })
})
