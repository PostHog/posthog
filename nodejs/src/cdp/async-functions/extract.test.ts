import jwt from 'jsonwebtoken'

import { defaultConfig } from '~/common/config/config'
import { parseJSON } from '~/common/utils/json-parse'
import * as requestModule from '~/common/utils/request'

import { createExampleInvocation } from '../_tests/fixtures'
import { AsyncFunctionContext, getAsyncFunctionHandler } from '../async-function-registry'
import { MinimalLogEntry } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import './extract'

describe('postHogExtract', () => {
    const TASK_RUN_ID = '0198c9f1-0000-0000-0000-000000000002'
    const payload = {
        context: { message: 'Opened https://github.com/example/repo/pull/7 touching 3 files.' },
        fields: {
            pr_url: 'The URL of the pull request',
            files_changed: 'How many files the pull request changes',
            summary: 'One sentence on what changed',
        },
    }
    const hogFlow = {
        id: 'flow-1',
        actions: [
            {
                id: 'extract_1',
                output_variable: [
                    { key: 'pr_url', result_path: 'pr_url' },
                    { key: 'changed', result_path: 'files_changed' },
                    { key: 'everything', result_path: null },
                ],
            },
        ],
        variables: [
            { key: 'pr_url', type: 'string' },
            { key: 'changed', type: 'number' },
        ],
    }

    const invokeLive = async (args: Record<string, unknown>, flow = hogFlow): Promise<MinimalLogEntry[]> => {
        const example = createExampleInvocation()
        const invocation = { ...example, hogFlow: flow, state: { ...example.state, actionId: 'extract_1' } }
        const result = createInvocationResult<typeof invocation>(invocation)
        await getAsyncFunctionHandler('postHogExtract')!.execute(
            [args],
            {
                invocation,
                internalApiBaseUrl: defaultConfig.INTERNAL_API_BASE_URL,
                consumeInlineAsyncBudget: () => {},
            } as unknown as AsyncFunctionContext,
            result
        )
        return result.logs
    }

    let fetchSpy: jest.SpyInstance
    beforeEach(() => {
        fetchSpy = jest.spyOn(requestModule, 'internalFetch').mockResolvedValue({
            status: 200,
            text: () => Promise.resolve(JSON.stringify({ values: { pr_url: null, files_changed: 3, summary: null } })),
        } as requestModule.FetchResponse)
    })
    afterEach(() => jest.restoreAllMocks())

    it('types each field like the variable the step stores it in', async () => {
        await invokeLive(payload)

        const [url, options] = fetchSpy.mock.calls[0]
        expect(url).toMatch(/\/api\/projects\/1\/workflow_extractions\/$/)
        expect(parseJSON(options.body)).toEqual({
            context: payload.context,
            task_run_id: null,
            output_fields: [
                { name: 'pr_url', type: 'string', instruction: 'The URL of the pull request' },
                { name: 'files_changed', type: 'number', instruction: 'How many files the pull request changes' },
                { name: 'summary', type: 'string', instruction: 'One sentence on what changed' },
            ],
        })
        // Must exceed Django's 8 second gateway timeout so the worker receives its 503 instead of aborting first.
        expect(options.timeoutMs).toBeGreaterThan(8000)
        const token = options.headers.Authorization.replace('Bearer ', '')
        // The literal pins the dev default shared with Django's WORKFLOW_EXTRACT_JWT_SECRETS.
        // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
        const claims = jwt.verify(token, 'local-dev-workflow-extract-jwt', {
            audience: 'posthog:workflows:extract',
            algorithms: ['HS256'],
        }) as jwt.JwtPayload
        expect(claims).toMatchObject({ team_id: 1, hog_flow_id: 'flow-1' })
    })

    it('sends the AI task run so Django reads its full report in place of the text', async () => {
        await invokeLive({ ...payload, context: null, task_run_id: TASK_RUN_ID })

        expect(parseJSON(fetchSpy.mock.calls[0][1].body)).toMatchObject({ context: null, task_run_id: TASK_RUN_ID })
    })

    it('fails rather than guess the type of a result path that is not a field name', async () => {
        const arrayPath = {
            ...hogFlow,
            actions: [{ id: 'extract_1', output_variable: [{ key: 'changed', result_path: ['files_changed'] }] }],
        }

        await expect(invokeLive(payload, arrayPath as unknown as typeof hogFlow)).rejects.toThrow(
            /result path of changed/
        )
        expect(fetchSpy).not.toHaveBeenCalled()
    })

    it('ignores a stale mapping whose result path is no longer a field', async () => {
        const staleMapping = {
            ...hogFlow,
            actions: [
                {
                    id: 'extract_1',
                    output_variable: [
                        { key: 'pr_url', result_path: 'renamed_field' },
                        { key: 'changed', result_path: 'renamed_field' },
                    ],
                },
            ],
        }

        await invokeLive(payload, staleMapping)

        expect(fetchSpy).toHaveBeenCalled()
    })

    it('fails rather than store one field into variables of different types', async () => {
        const mixedTypes = {
            ...hogFlow,
            actions: [
                {
                    id: 'extract_1',
                    output_variable: [
                        { key: 'pr_url', result_path: 'files_changed' },
                        { key: 'changed', result_path: 'files_changed' },
                    ],
                },
            ],
        }

        await expect(invokeLive(payload, mixedTypes)).rejects.toThrow(/files_changed.*variables of one type/)
        expect(fetchSpy).not.toHaveBeenCalled()
    })

    it.each([
        ['the full report of the AI task run', { task_run_id: TASK_RUN_ID }, /full report of AI task run 0198c9f1/],
        ['the text to read', {}, /Text to read/],
    ])('logs that the model reads %s', async (_name, source, expected) => {
        const logs = await invokeLive({ ...payload, ...source })

        expect(logs.map((log) => log.message)).toEqual([expect.stringMatching(expected)])
    })

    it('returns no value for any field when mocked', () => {
        const logs: MinimalLogEntry[] = []

        const response = getAsyncFunctionHandler('postHogExtract')!.mock([payload], logs)

        expect(response).toEqual({
            status: 200,
            body: { values: { pr_url: null, files_changed: null, summary: null } },
        })
        expect(logs[0].message).toMatch(/mocked/)
    })

    it.each([
        ['no fields', { ...payload, fields: {} }, /Enter at least one field/],
        [
            'twenty-one fields',
            { ...payload, fields: Object.fromEntries(Array.from({ length: 21 }, (_, i) => [`f${i}`, 'x'])) },
            /at most 20 fields/,
        ],
        [
            'a field name with spaces',
            { ...payload, fields: { 'pr url': 'The URL' } },
            /letters, digits and underscores/,
        ],
        ['a blank instruction', { ...payload, fields: { pr_url: ' ' } }, /Say what to put in pr_url/],
        [
            'a long instruction',
            { ...payload, fields: { pr_url: 'x'.repeat(501) } },
            /instructions to 500 characters or fewer/,
        ],
        [
            'an oversized text to read',
            { ...payload, context: { message: 'x'.repeat(65_536) } },
            /Keep the text to read to 65536 characters of JSON/,
        ],
        [
            'a field name over 64 characters',
            { ...payload, fields: { ['a'.repeat(65)]: 'x' } },
            /keep it to 64 characters/,
        ],
        ['an AI task run that is not a run ID', { ...payload, task_run_id: 'latest' }, /AI task run/],
        ['no text and no AI task run', { ...payload, context: null }, /Enter the text to read, or an AI task run/],
    ])('rejects %s in both mocked and live calls', async (_name, args, expected) => {
        expect(() => getAsyncFunctionHandler('postHogExtract')!.mock([args], [] as MinimalLogEntry[])).toThrow(expected)
        await expect(invokeLive(args)).rejects.toThrow(expected)
        expect(fetchSpy).not.toHaveBeenCalled()
    })
})
