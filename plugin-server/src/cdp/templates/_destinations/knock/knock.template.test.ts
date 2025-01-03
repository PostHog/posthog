import { HogFunctionInvocationGlobals } from 'cdp/types'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './knock.template'

describe('knock template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(new Date('2025-01-01'))
    })

    const createInputs = (overrides = {}) => ({
        webhookUrl: 'https://api.knock.app/integrations/receive/tkN_P18rTjBq30waf1RLp',
        include_all_properties: false,
        userId: 'edad9282-25d0-4cf1-af0e-415535ee1161',
        attributes: { phone: '0123456789' },
        ...overrides,
    })

    const defaultEvent: HogFunctionInvocationGlobals['event'] = {
        uuid: '9d67cc3f-edf7-490d-b311-f03c21c64caf',
        distinct_id: '8b9c729c-c59b-4c39-b5a6-af9fa1233054',
        event: '$pageview',
        timestamp: '2024-09-16T16:11:48.577Z',
        url: 'http://localhost:8000/project/1/events/',
        properties: {
            $current_url:
                'http://localhost:8000/project/1/pipeline/destinations/hog-0191fb90-bb37-0000-fba4-3377db3ac5e6/configuration',
            $browser: 'Chrome',
            price: 15,
            phone: '0123456789',
        },
        elements_chain: '',
    }

    it('should invoke the function successfully', async () => {
        const response = await tester.invoke(createInputs(), {
            event: defaultEvent,
        } as any)

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queue).toEqual('fetch')
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            Object {
              "body": "{\\"type\\":\\"track\\",\\"event\\":\\"$pageview\\",\\"userId\\":\\"edad9282-25d0-4cf1-af0e-415535ee1161\\",\\"properties\\":{\\"phone\\":\\"0123456789\\"},\\"messageId\\":\\"9d67cc3f-edf7-490d-b311-f03c21c64caf\\",\\"timestamp\\":\\"2024-09-16T16:11:48.577Z\\"}",
              "headers": Object {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://api.knock.app/integrations/receive/tkN_P18rTjBq30waf1RLp",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: JSON.stringify({ ok: true }),
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('should include all properties if set', async () => {
        const response = await tester.invoke(createInputs({ include_all_properties: false }), {
            event: defaultEvent,
        })

        expect(JSON.parse(response.invocation.queueParameters?.body ?? '').properties).toEqual({
            phone: '0123456789',
        })

        const response2 = await tester.invoke(createInputs({ include_all_properties: true }), {
            event: defaultEvent,
        })

        expect(JSON.parse(response2.invocation.queueParameters?.body ?? '').properties).toEqual({
            $current_url:
                'http://localhost:8000/project/1/pipeline/destinations/hog-0191fb90-bb37-0000-fba4-3377db3ac5e6/configuration',
            $browser: 'Chrome',
            price: 15,
            phone: '0123456789',
        })
    })

    it('should require identifier', async () => {
        const response = await tester.invoke(createInputs({ userId: '' }))

        expect(response.finished).toBe(true)
        expect(response.logs.filter((l) => l.level === 'info')[0].message).toMatchInlineSnapshot(
            `"No User ID set. Skipping..."`
        )
    })
})
