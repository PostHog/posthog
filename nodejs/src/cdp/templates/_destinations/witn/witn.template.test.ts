import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './witn.template'

describe('witn template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const baseInputs = {
        api_key: 'witn-api-key',
        api_base_url: 'https://api.thewitn.com',
        key: 'support:ticket:1001',
        action: 'csat_received',
        customer_key: 'acme',
        agent_key: '',
        idempotency_key: 'event-id',
        timestamp: '2024-01-01T00:00:00Z',
        properties: {
            value: 0,
            attribution: 0.8,
            settles_at: '',
        },
    }

    it('sends an event to witn', async () => {
        const response = await tester.invoke(baseInputs)

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)
        expect(response.invocation.queueParameters).toMatchObject({
            url: 'https://api.thewitn.com/v1/events',
            method: 'POST',
            headers: {
                Authorization: 'Bearer witn-api-key',
                'Content-Type': 'application/json',
            },
        })
        expect(parseJSON((response.invocation.queueParameters as any).body)).toEqual({
            key: 'support:ticket:1001',
            action: 'csat_received',
            customer_key: 'acme',
            timestamp: '2024-01-01T00:00:00Z',
            idempotency_key: 'event-id',
            properties: {
                value: 0,
                attribution: 0.8,
            },
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 202,
            body: {},
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('includes the agent key when configured', async () => {
        const response = await tester.invoke({
            ...baseInputs,
            agent_key: 'support',
            properties: {},
        })

        expect(parseJSON((response.invocation.queueParameters as any).body)).toMatchObject({
            agent_key: 'support',
        })
    })

    it('throws an error if the witn API request fails', async () => {
        let response = await tester.invoke(baseInputs)

        response = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: {
                error: {
                    code: 'VALIDATION_ERROR',
                    message: 'Invalid request',
                },
            },
        })

        expect(response.error).toMatchInlineSnapshot(
            `"Error from witn API (status 400): {'error': {'code': 'VALIDATION_ERROR', 'message': 'Invalid request'}}"`
        )
    })
})
