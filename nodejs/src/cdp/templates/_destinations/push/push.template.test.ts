import { TemplateTester } from '../../test/test-helpers'
import { template } from './push.template'

describe('push template', () => {
    // The empty mapping_templates only clears old mappings, and the tester refuses any mapping list.
    const tester = new TemplateTester({ ...template, mapping_templates: undefined })

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it.each([
        ['nothing set', {}, undefined, undefined],
        [
            'link and group',
            { link: 'myapp://chat/123', group: 'chat-123' },
            { link: 'myapp://chat/123', group: 'chat-123' },
            'chat-123',
        ],
        [
            'the link field replaces a link key in custom data',
            { link: 'https://example.com/a', data: { kind: 'dm', link: 'stale' } },
            { kind: 'dm', link: 'https://example.com/a' },
            undefined,
        ],
        [
            'iOS thread ID wins over the group',
            { group: 'chat-123', ios_threadId: 'thread-9' },
            { group: 'chat-123' },
            'thread-9',
        ],
    ])('%s', async (_name, inputs, expectedData, expectedThreadId) => {
        const response = await tester.invoke({ channels: [{ $integration_id: 1 }], ...inputs })

        expect(response.error).toBeUndefined()
        const payload = (response.invocation.queueParameters as any).payload
        expect(payload.data).toEqual(expectedData)
        expect(payload.apns?.threadId).toEqual(expectedThreadId)
    })
})
