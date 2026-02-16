import { TemplateTester } from '../../test/test-helpers'
import { template } from './_default.template'

describe('warehouse source default template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it.each([
        ['simple object', { type: 'event', data: { id: '123' } }],
        ['nested object', { a: { b: { c: 'deep' } }, list: [1, 2, 3] }],
        ['empty object', {}],
    ])('should return the request body as-is for %s', async (_label, body) => {
        const response = await tester.invoke(
            {},
            { request: { method: 'POST', headers: {}, body, stringBody: JSON.stringify(body), query: {} } }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.execResult).toEqual(body)
    })
})
