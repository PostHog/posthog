import api from 'lib/api'

import {
    canvasesActionsInvoke,
    canvasesActionsRetrieve,
    canvasesConnectorsCall,
    canvasesToolsInvoke,
} from '../generated/api'
import { CanvasDataBridge } from './canvasDataBridge'

jest.mock('../generated/api')
jest.mock('lib/api')

describe('CanvasDataBridge query routing', () => {
    const bridge = (): CanvasDataBridge =>
        new CanvasDataBridge(
            () => ({
                projectId: '1',
                canvasId: 'canvas-1',
                sourceVersionId: 'v1',
                captureToken: null,
                distinctId: null,
            }),
            {
                confirmAction: jest.fn(),
                confirmAgentRequest: jest.fn(),
                requestConnectorPermission: jest.fn(),
                hasUserActivation: () => true,
            }
        )

    beforeEach(() => {
        jest.mocked(api.query).mockReset().mockResolvedValue({ results: [], columns: [] })
    })

    test.each([
        '../tasks/example-task/run',
        '..\\tasks\\example-task\\run',
        '%2e%2e/tasks/example-task/run',
        'UnknownQuery',
    ])('rejects an unrecognized query kind before any request: %s', async (kind) => {
        await expect(bridge().handle('query', { query: { kind } })).rejects.toThrow()
        expect(api.query).not.toHaveBeenCalled()
    })

    const tags = { productKey: 'canvas', scene: 'Canvas' }

    test.each([
        {
            input: { query: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: '$pageview' }] } },
            sent: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: '$pageview' }], tags },
        },
        {
            input: { query: { kind: 'HogQLQuery', query: 'SELECT 1', tags: { productKey: 'spoofed', name: 'n' } } },
            sent: { kind: 'HogQLQuery', query: 'SELECT 1', tags: { ...tags, name: 'n' } },
        },
        {
            input: { query: { kind: 'DataTableNode', source: { kind: 'HogQLQuery', query: 'SELECT 1' } } },
            sent: { kind: 'DataTableNode', source: { kind: 'HogQLQuery', query: 'SELECT 1', tags }, tags },
        },
        {
            input: { query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } } },
            sent: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [], tags } },
        },
        {
            input: { query: { kind: 'InsightActorsQuery', source: { kind: 'TrendsQuery', series: [] } } },
            sent: { kind: 'InsightActorsQuery', source: { kind: 'TrendsQuery', series: [], tags }, tags },
        },
        {
            input: { query: { kind: 'WebAnalyticsExternalSummaryQuery', dateRange: {} } },
            sent: { kind: 'WebAnalyticsExternalSummaryQuery', dateRange: {} },
        },
        { input: { hogql: 'SELECT 1' }, sent: { kind: 'HogQLQuery', query: 'SELECT 1', tags } },
    ])('runs a supported query tagged as canvas: %j', async ({ input, sent }) => {
        await expect(bridge().handle('query', input)).resolves.toEqual({ results: [], columns: [] })
        expect(api.query).toHaveBeenCalledWith(sent, { refresh: 'blocking' })
    })
})

describe('CanvasDataBridge action confirmation', () => {
    test.each([false, true])('only starts a paid task after approval: %s', async (allowed) => {
        const action = {
            verb: 'tasks.create_and_run',
            summary: 'Start a cloud task.',
            destructive: false,
            usage: '',
        }
        const payload = {
            title: 'Check example chart',
            description: 'Check the example chart.',
            idempotency_key: 'one',
        }
        jest.mocked(canvasesActionsRetrieve).mockResolvedValue({ actions: [action], tools: [] })
        jest.mocked(canvasesActionsInvoke)
            .mockReset()
            .mockResolvedValue({ verb: action.verb, result: { task_id: 'task-1' } })
        const confirmAction = jest.fn(async () => {
            expect(canvasesActionsInvoke).not.toHaveBeenCalled()
            return allowed
        })
        const bridge = new CanvasDataBridge(
            () => ({
                projectId: '1',
                canvasId: 'canvas-1',
                sourceVersionId: 'v1',
                captureToken: null,
                distinctId: null,
            }),
            {
                confirmAction,
                confirmAgentRequest: jest.fn(),
                requestConnectorPermission: jest.fn(),
                hasUserActivation: () => true,
            }
        )

        const result = bridge.handle('actionInvoke', { verb: action.verb, payload })
        if (allowed) {
            await expect(result).resolves.toEqual({ verb: action.verb, result: { task_id: 'task-1' } })
            expect(canvasesActionsInvoke).toHaveBeenCalledWith('1', 'canvas-1', { verb: action.verb, payload })
        } else {
            await expect(result).rejects.toThrow('Canvas action canceled')
            expect(canvasesActionsInvoke).not.toHaveBeenCalled()
        }
        expect(confirmAction).toHaveBeenCalledWith({ action, payload })
    })

    const writeTool = {
        name: 'feature-flag-enable',
        title: 'Enable feature flag',
        summary: 'Enable feature flag',
        read_only: false,
        destructive: false,
    }
    const readTool = { ...writeTool, name: 'feature-flag-get-definition', read_only: true }

    test.each([
        // A canvas must not change data from a load or render, so reads take read-only tools only.
        { method: 'toolRead', tool: writeTool, allowed: true, error: 'changes data' },
        { method: 'toolCall', tool: writeTool, allowed: false, error: 'Canvas tool call canceled' },
        { method: 'toolCall', tool: writeTool, allowed: true, error: null },
        { method: 'toolRead', tool: readTool, allowed: false, error: null },
    ])('$method of $tool.name with approval $allowed', async ({ method, tool, allowed, error }) => {
        jest.mocked(canvasesActionsRetrieve).mockResolvedValue({ actions: [], tools: [writeTool, readTool] })
        jest.mocked(canvasesToolsInvoke)
            .mockReset()
            .mockResolvedValue({ tool: tool.name, result: { id: 7 } })
        const confirmAction = jest.fn(async () => allowed)
        const bridge = new CanvasDataBridge(
            () => ({
                projectId: '1',
                canvasId: 'canvas-1',
                sourceVersionId: 'v1',
                captureToken: null,
                distinctId: null,
            }),
            {
                confirmAction,
                confirmAgentRequest: jest.fn(),
                requestConnectorPermission: jest.fn(),
                hasUserActivation: () => true,
            }
        )

        const result = bridge.handle(method, { tool: tool.name, arguments: { id: 7 } })

        if (error) {
            await expect(result).rejects.toThrow(error)
            expect(canvasesToolsInvoke).not.toHaveBeenCalled()
        } else {
            await expect(result).resolves.toEqual({ id: 7 })
            expect(canvasesToolsInvoke).toHaveBeenCalledWith('1', 'canvas-1', { tool: tool.name, arguments: { id: 7 } })
        }
        expect(confirmAction).toHaveBeenCalledTimes(method === 'toolCall' && !tool.read_only ? 1 : 0)
    })
})

describe('CanvasDataBridge connector consent', () => {
    test.each([
        {
            allowed: true,
            outcome: { status: 'fulfilled', value: expect.objectContaining({ status: 'ok' }) },
            apiCalls: 4,
        },
        {
            allowed: false,
            outcome: {
                status: 'rejected',
                reason: expect.objectContaining({ message: expect.stringContaining('not granted') }),
            },
            apiCalls: 0,
        },
    ])('parallel calls for one tool share one prompt, allowed: $allowed', async ({ allowed, outcome, apiCalls }) => {
        jest.mocked(canvasesConnectorsCall)
            .mockReset()
            .mockResolvedValue({
                status: 'ok',
                result: { items: [] },
                detail: '',
                truncated: false,
                connect_path: null,
                approval_token: null,
            })
        let answer!: (allowed: boolean) => void
        const requestConnectorPermission = jest.fn(
            () =>
                new Promise<boolean>((resolve) => {
                    answer = resolve
                })
        )
        const bridge = new CanvasDataBridge(
            () => ({
                projectId: '1',
                canvasId: 'canvas-1',
                sourceVersionId: 'v1',
                captureToken: null,
                distinctId: null,
            }),
            {
                confirmAction: jest.fn(),
                confirmAgentRequest: jest.fn(),
                requestConnectorPermission,
                hasUserActivation: () => false,
            }
        )
        const call = (page: number): Promise<unknown> =>
            bridge.handle('connectorCall', { provider: 'github', tool: 'list_pull_requests', arguments: { page } })

        const parallel = Promise.allSettled([1, 2, 3].map(call))
        answer(allowed)
        // The fourth call starts after the answer, so it reads the stored answer and neither
        // asks again nor reopens a denied prompt without a click.
        const outcomes = [...(await parallel), ...(await Promise.allSettled([call(4)]))]

        expect(outcomes).toEqual(Array(4).fill(outcome))
        expect(requestConnectorPermission).toHaveBeenCalledTimes(1)
        expect(canvasesConnectorsCall).toHaveBeenCalledTimes(apiCalls)
    })
})
