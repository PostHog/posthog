import { TemplateTester } from '../../test/test-helpers'
import { template } from './push.template'

describe('push template', () => {
    // The template clears its mappings with an empty list, which the tester reads as having mappings.
    const tester = new TemplateTester({ ...template, mapping_templates: undefined })

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it.each([
        {
            delivery: undefined,
            payload: { title: 'Hi', body: 'There', image: 'https://example.com/i.png', data: { k: 'v' } },
        },
        {
            delivery: 'notification',
            payload: { title: 'Hi', body: 'There', image: 'https://example.com/i.png', data: { k: 'v' } },
        },
        {
            delivery: 'android_data_only',
            payload: {
                delivery: 'android_data_only',
                title: 'Hi',
                body: 'There',
                image: 'https://example.com/i.png',
                data: { k: 'v' },
            },
        },
        { delivery: 'silent', payload: { delivery: 'silent', data: { k: 'v' } } },
    ])('builds the payload for delivery $delivery', async ({ delivery, payload }) => {
        const response = await tester.invoke({
            distinctId: 'user-1',
            channels: [{ $integration_id: 1 }],
            delivery,
            title: 'Hi',
            body: 'There',
            image: 'https://example.com/i.png',
            data: { k: 'v' },
        })

        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchObject({ type: 'sendPushNotification', payload })
        expect((response.invocation.queueParameters as any).payload).toEqual(payload)
    })
})
