import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-show-survey.template'

describe('posthog show survey template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
        jest.spyOn(Date, 'now').mockReturnValue(DateTime.fromISO('2025-01-01T00:00:00Z').toMillis())
    })

    it('marks the person as triggered for the survey', async () => {
        const response = await tester.invoke(
            { survey_id: '0190-survey', distinct_id: '{event.distinct_id}' },
            { event: { event: 'signed_up', distinct_id: 'distinct-id', properties: {} } }
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.capturedPostHogEvents).toEqual([
            expect.objectContaining({
                event: '$set',
                distinct_id: 'distinct-id',
                properties: expect.objectContaining({ $set: { '$survey_triggered/0190-survey': true } }),
            }),
        ])
    })

    it.each([
        ['survey', { survey_id: '', distinct_id: 'distinct-id' }, 'A survey is required'],
        [
            'distinct ID',
            { survey_id: '0190-survey', distinct_id: '{event.properties.missing}' },
            'Distinct ID is required',
        ],
    ])('fails without a %s', async (_, inputs, error) => {
        const response = await tester.invoke(inputs, {
            event: { event: 'signed_up', distinct_id: 'distinct-id', properties: {} },
        })
        expect(response.error).toEqual(error)
        expect(response.capturedPostHogEvents).toEqual([])
    })
})
