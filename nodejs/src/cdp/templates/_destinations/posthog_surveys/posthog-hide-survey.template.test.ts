import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-hide-survey.template'

describe('posthog hide survey template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('removes the survey trigger from the person', async () => {
        const response = await tester.invoke(
            { survey_id: '0190-survey', distinct_id: '{event.distinct_id}' },
            { event: { event: 'survey sent', distinct_id: 'distinct-id', properties: {} } }
        )
        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toEqual([
            expect.objectContaining({
                event: '$set',
                distinct_id: 'distinct-id',
                properties: expect.objectContaining({ $unset: ['$survey_triggered/0190-survey'] }),
            }),
        ])
    })

    it('fails without a survey', async () => {
        const response = await tester.invoke(
            { survey_id: '', distinct_id: 'distinct-id' },
            { event: { event: 'survey sent', distinct_id: 'distinct-id', properties: {} } }
        )
        expect(response.error).toEqual('A survey is required')
        expect(response.capturedPostHogEvents).toEqual([])
    })
})
