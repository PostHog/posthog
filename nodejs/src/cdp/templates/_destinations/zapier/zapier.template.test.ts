import { TemplateTester } from '../../test/test-helpers'
import { template } from './zapier.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    hook: 'hooks/1/2',
    body: { hello: 'world' },
    debug: false,
    ...overrides,
})
describe('zapier template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('posts to the hook', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "body": "{"hello":"world"}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://hooks.zapier.com/hooks/1/2",
            }
        `
        )
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'success' },
        })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    })
    /*
     * People paste the whole webhook URL as often as the path, so the template normalizes
     * both onto the same target.
     */ it.each([
        ['a bare path', 'hooks/catch/123456/abcdef/'],
        ['a full url', 'https://hooks.zapier.com/hooks/catch/123456/abcdef/'],
        ['a leading slash', '/hooks/catch/123456/abcdef/'],
    ])('normalizes %s', async (_name, hook) => {
        const response = await tester.invoke(createInputs({ hook }))
        expect((response.invocation.queueParameters as any).url).toEqual(
            'https://hooks.zapier.com/hooks/catch/123456/abcdef/'
        )
    })
    it('logs the response when debug is on', async () => {
        const response = await tester.invoke(createInputs({ debug: true }))
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: 'ok' })
        expect(fetchResponse.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContainEqual(
            expect.stringContaining('Response, 200')
        )
    })
    /*
     * The template never inspects the status, so a rejected hook finishes cleanly.
     * Zapier hooks go stale silently, and this records that we do not surface that.
     */ it('ignores a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, { status: 410, body: 'Gone' })
        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
    })
})
