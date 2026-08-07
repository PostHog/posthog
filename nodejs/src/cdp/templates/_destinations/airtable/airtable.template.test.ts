import { TemplateTester } from '../../test/test-helpers'
import { template } from './airtable.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    access_token: 'test_token',
    base_id: 'test_base_id',
    table_name: 'test_table',
    fields: { Name: 'John Doe', Email: 'john@example.com' },
    debug: false,
    ...overrides,
})
describe('airtable template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('creates the record', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "body": "{"fields":{"Name":"John Doe","Email":"john@example.com"},"typecast":true}",
              "headers": {
                "Authorization": "Bearer test_token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.airtable.com/v0/test_base_id/test_table",
            }
        `
        )
        expect(response.logs.filter((l) => l.level === 'info')).toEqual([])
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { id: 'rec123' },
        })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    })
    it('logs the request and response when debug is on', async () => {
        const response = await tester.invoke(createInputs({ debug: true }))
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { id: 'rec123' },
        })
        const messages = [...response.logs, ...fetchResponse.logs]
            .filter((l) => l.level === 'info')
            .map((l) => l.message)
        expect(messages.some((m) => m.startsWith('Request,'))).toBe(true)
        expect(messages.some((m) => m.startsWith('Response, 200'))).toBe(true)
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 422,
            body: { error: 'INVALID_REQUEST' },
        })
        expect(result.error).toMatchInlineSnapshot(
            `"Error from api.airtable.com (status 422): {'error': 'INVALID_REQUEST'}"`
        )
    })
})
