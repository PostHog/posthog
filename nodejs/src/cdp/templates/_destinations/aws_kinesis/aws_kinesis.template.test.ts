import { TemplateTester } from '../../test/test-helpers'
import { template } from './aws_kinesis.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    aws_access_key_id: 'aws_access_key_id',
    aws_secret_access_key: 'aws_secret_access_key',
    aws_region: 'aws_region',
    aws_kinesis_stream_name: 'aws_kinesis_stream_arn',
    aws_kinesis_partition_key: '1',
    payload: { hello: 'world' },
    ...overrides,
})
describe('aws kinesis template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    /*
     * The template hands signing to the cyclotron fetch executor, which re-signs on every
     * attempt. The aws_sigv4 bag carries input-key references rather than credential values,
     * so secrets never enter the plaintext queue payload — that is what the snapshot locks in.
     */ it('puts the record', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "aws_sigv4": {
                "access_key_id_input": "aws_access_key_id",
                "region": "aws_region",
                "secret_access_key_input": "aws_secret_access_key",
                "service": "kinesis",
              },
              "body": "{"StreamName":"aws_kinesis_stream_arn","PartitionKey":"1","Data":"eyJoZWxsbyI6IndvcmxkIn0="}",
              "headers": {
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": "Kinesis_20131202.PutRecord",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://kinesis.aws_region.amazonaws.com",
            }
        `
        )
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: {} })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain(
            'Event sent successfully!'
        )
    })
    it('generates a partition key when none is given', async () => {
        const response = await tester.invoke(createInputs({ aws_kinesis_partition_key: null }))
        const body = (response.invocation.queueParameters as any).body
        expect(body).toMatch(/"PartitionKey":"[0-9a-f-]{36}"/)
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 403,
            body: { message: 'denied' },
        })
        expect(result.error).toMatchInlineSnapshot(
            `"Error from aws_region.amazonaws.com (status 403): {'message': 'denied'}"`
        )
    })
})
