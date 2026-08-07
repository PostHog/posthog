import { TemplateTester } from '../../test/test-helpers'
import { template } from './gcs.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    auth: { access_token: 'ACCESS_TOKEN' },
    bucketName: 'my-bucket',
    filename: '2024-01-01/20240101-000000-event-id.csv',
    payload: 'uuid,event\nevent-id,event-name',
    ...overrides,
})
describe('google cloud storage template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('uploads the object', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "body": "uuid,event
            event-id,event-name",
              "headers": {
                "Authorization": "Bearer ACCESS_TOKEN",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://storage.googleapis.com/upload/storage/v1/b/my-bucket/o?uploadType=media&name=2024-01-01%2F20240101-000000-event-id.csv",
            }
        `
        )
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { name: 'object' },
        })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain(
            'Event sent successfully!'
        )
    }) /* Bucket and filename go into the URL, so both have to be percent-encoded. */
    it('url-encodes the bucket and filename', async () => {
        const response = await tester.invoke(createInputs({ bucketName: 'my bucket/prod', filename: 'a b/c+d.csv' }))
        expect((response.invocation.queueParameters as any).url).toEqual(
            'https://storage.googleapis.com/upload/storage/v1/b/my%20bucket%2Fprod/o?uploadType=media&name=a%20b%2Fc%2Bd.csv'
        )
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 403,
            body: { error: 'forbidden' },
        })
        expect(result.error).toMatchInlineSnapshot(`"Error sending event"`)
    })
})
