import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-query.template'

describe('posthog query template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should invoke the async function with the query', async () => {
        const response = await tester.invoke({
            query: 'SELECT event, count() FROM events GROUP BY event',
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"query":{"kind":"HogQLQuery","query":"SELECT event, count() FROM events GROUP BY event"}}",
              "headers": {
                "Authorization": "Bearer ",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "http://localhost:8000/api/environments/1/query/",
            }
        `)
    })

    it('should return the response body on success', async () => {
        const response = await tester.invoke({
            query: 'SELECT event, count() FROM events GROUP BY event',
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: {
                columns: ['event', 'count'],
                results: [
                    ['pageview', 1000],
                    ['$autocapture', 500],
                ],
                hasMore: false,
            },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.execResult).toMatchInlineSnapshot(`
            {
              "columns": [
                "event",
                "count",
              ],
              "hasMore": false,
              "results": [
                [
                  "pageview",
                  1000,
                ],
                [
                  "$autocapture",
                  500,
                ],
              ],
            }
        `)
    })

    it('should throw an error when query fails', async () => {
        const response = await tester.invoke({
            query: 'SELECT invalid FROM events',
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { error: 'Invalid query' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatchInlineSnapshot(`"Query failed with status: 400"`)
    })

    it('should throw an error when query is empty', async () => {
        const response = await tester.invoke({
            query: '',
        })

        expect(response.finished).toBe(true)
        expect(response.error).toMatchInlineSnapshot(`"Query is required"`)
    })
})
