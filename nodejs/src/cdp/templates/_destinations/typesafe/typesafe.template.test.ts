import * as cdpFetch from '~/cdp/utils/cdp-fetch'
import * as envUtils from '~/common/utils/env-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { FetchResponse } from '~/common/utils/request'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './typesafe.template'

describe('TypeSafe classification template', () => {
    const tester = new TemplateTester(template, { executionTimeoutMs: 30_000 })
    const inputs = {
        api_key: 'fake-typesafe-key',
        question: 'Which activity does the text describe?',
        context: { text: '{event.properties.text}' },
        categories: { painting: 'Painting a picture', gardening: 'Growing plants', other: 'Any other activity' },
    }

    beforeEach(async () => {
        await tester.beforeEach()
    })
    afterEach(() => tester.afterEach())

    it('adds the API key only for the HTTP request and resolves it again on retry', async () => {
        const response = (status: number): FetchResponse =>
            ({ status, text: () => Promise.resolve('{}'), dump: () => Promise.resolve() }) as FetchResponse
        const fetch = jest
            .spyOn(cdpFetch, 'cdpTrackedFetch')
            .mockResolvedValueOnce({ fetchResponse: response(503), fetchDuration: 1, fetchError: null })
            .mockResolvedValueOnce({ fetchResponse: response(200), fetchDuration: 1, fetchError: null })
        try {
            const pending = await tester.invoke({ ...inputs, context: 'Example context' })
            pending.invocation.state = parseJSON(JSON.stringify(pending.invocation.state))
            expect(JSON.stringify(pending.invocation.state)).not.toContain(inputs.api_key)
            const retry = await tester.executeFetch(pending.invocation)
            expect(fetch.mock.calls[0][0].fetchParams.headers).toMatchObject({
                Authorization: `Bearer ${inputs.api_key}`,
            })
            expect(retry.invocation.queueParameters?.type).toBe('fetch')
            expect(JSON.stringify(retry.invocation.queueParameters)).not.toContain(inputs.api_key)
            expect(JSON.stringify(retry.invocation.state)).not.toContain(inputs.api_key)
            retry.invocation.hogFunction.inputs!.api_key = { value: 'rotated-fake-key' }
            await tester.executeFetch(retry.invocation)
            expect(fetch.mock.calls[1][0].fetchParams.headers).toMatchObject({
                Authorization: 'Bearer rotated-fake-key',
            })
        } finally {
            fetch.mockRestore()
        }
    })

    it.each([
        [true, false],
        [false, true],
    ])('blocks requests in production (%s) and Cloud (%s)', async (production, cloud) => {
        const productionCheck = jest.spyOn(envUtils, 'isProdEnv').mockReturnValue(production)
        const cloudCheck = jest.spyOn(envUtils, 'isCloud').mockReturnValue(cloud)
        const fetch = jest.spyOn(cdpFetch, 'cdpTrackedFetch')
        try {
            const pending = await tester.invoke({ ...inputs, context: 'Example context' })
            const result = await tester.executeFetch(pending.invocation)
            expect(result.error?.message).toContain('only in local development')
            expect(fetch).not.toHaveBeenCalled()
        } finally {
            productionCheck.mockRestore()
            cloudCheck.mockRestore()
            fetch.mockRestore()
        }
    })

    it('rejects conflicting authentication before sending a request', async () => {
        const fetch = jest.spyOn(cdpFetch, 'cdpTrackedFetch')
        try {
            const pending = await tester.invoke({ ...inputs, context: 'Example context' })
            if (pending.invocation.queueParameters?.type !== 'fetch') {
                throw new Error('Expected a queued request')
            }
            pending.invocation.queueParameters.aws_sigv4 = {
                service: 'sqs',
                region: 'us-east-1',
                access_key_id_input: 'access_key',
                secret_access_key_input: 'secret_key',
            }
            const result = await tester.executeFetch(pending.invocation)
            expect(result.error?.message).toContain('either AWS signing or bearer authentication')
            expect(fetch).not.toHaveBeenCalled()
        } finally {
            fetch.mockRestore()
        }
    })

    it.each([0.2, 0.95])('returns the category and confidence (%s) for later steps', async (confidence) => {
        const pending = await tester.invoke(inputs, {
            event: { properties: { text: 'I planted a row of carrots.', private_note: 'Do not send this.' } },
        })
        expect(pending.error).toBeUndefined()
        expect(pending.finished).toBe(false)
        expect(pending.invocation.queueParameters).toEqual({
            type: 'fetch',
            url: 'https://api.typesafe.ai/v1/systemone',
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            bearer_token_input: 'api_key',
            body: JSON.stringify({
                model: 'jev-1.13.0',
                state: { text: 'I planted a row of carrots.' },
                questions: {
                    category: { type: 'choice', instructions: inputs.question, criteria: inputs.categories },
                },
            }),
        })
        expect(JSON.stringify(pending.invocation.queueParameters)).not.toContain(inputs.api_key)
        expect(JSON.stringify(pending.invocation.state)).not.toContain(inputs.api_key)
        const result = await tester.invokeFetchResponse(pending.invocation, {
            status: 200,
            body: { answers: { category: { type: 'choice', choice: 'gardening', confidence, extra: 'ignore' } } },
        })
        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
        expect(result.execResult).toEqual({ category: 'gardening', confidence })
    })

    it.each([
        [401, { detail: 'private provider response' }],
        [429, {}],
        [503, {}],
        [200, {}],
        [200, { answers: { category: { type: 'choice', choice: 'unknown', confidence: 0.9 } } }],
        [200, { answers: { category: { type: 'choice', choice: 'gardening', confidence: '0.9' } } }],
        [200, { answers: { category: { type: 'choice', choice: 'gardening', confidence: 2 } } }],
        [200, { answers: { category: { type: 'choice', choice: 'gardening', confidence: null } } }],
    ])('fails without exposing provider content (%s, %j)', async (status, body) => {
        const pending = await tester.invoke({ ...inputs, context: 'Example context' })
        const result = await tester.invokeFetchResponse(pending.invocation, { status, body })
        expect(result.error).toMatch(/TypeSafe/)
        expect(JSON.stringify(result.logs)).not.toContain('private provider response')
        expect(JSON.stringify(result.logs)).not.toContain(inputs.api_key)
    })

    it.each([
        { categories: {} },
        { categories: [] },
        { categories: { gardening: 1 } },
        { context: '' },
        { question: '' },
    ])('rejects incomplete inputs before making a request (%j)', async (invalid) => {
        const result = await tester.invoke({ ...inputs, context: 'Example context', ...invalid })
        expect(result.error).toMatch(/TypeSafe/)
        expect(result.invocation.queueParameters).toBeUndefined()
    })
})
