import api from 'lib/api'

import { canvasesActionsInvoke, canvasesActionsRetrieve, canvasesConnectorsCall } from '../generated/api'
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
                confirmPostHogWrite: jest.fn(),
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
        jest.mocked(canvasesActionsRetrieve).mockResolvedValue({ actions: [action] })
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
                confirmPostHogWrite: jest.fn(),
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
})

describe('CanvasDataBridge PostHog tools', () => {
    const okResult = {
        status: 'ok',
        result: { content: [], structured_content: { version: 3 }, is_error: false },
        detail: '',
        truncated: false,
        connect_path: null,
        approval_token: null,
        confirmation: null,
    } as const
    const pendingWrite = {
        ...okResult,
        status: 'needs_approval',
        result: null,
        approval_token: 'approval-token',
        confirmation: { title: 'Set feature flag release condition rollout', destructive: false },
    } as const
    const read = { provider: 'posthog', tool: 'feature-flag-get-definition', arguments: { id: 7 } }
    const write = {
        provider: 'posthog',
        tool: 'feature-flag-set-release-condition-rollout',
        arguments: { id: 7, condition_index: 0, rollout_percentage: 50, version: 3 },
    }

    const setup = (
        options: { hasUserActivation?: boolean; confirm?: boolean } = {}
    ): { bridge: CanvasDataBridge; confirmPostHogWrite: jest.Mock } => {
        const confirmPostHogWrite = jest.fn(async () => options.confirm ?? true)
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
                requestConnectorPermission: jest.fn(async () => true),
                confirmPostHogWrite,
                hasUserActivation: () => options.hasUserActivation ?? true,
            }
        )
        return { bridge, confirmPostHogWrite }
    }

    beforeEach(() => {
        jest.mocked(canvasesConnectorsCall).mockReset()
    })

    test('a confirmed write sends the approval once and is never served from the read cache', async () => {
        jest.mocked(canvasesConnectorsCall).mockImplementation(async (_project, _canvas, body) =>
            body.tool === write.tool && !body.approval_token ? pendingWrite : okResult
        )
        const { bridge, confirmPostHogWrite } = setup()

        for (let attempt = 0; attempt < 2; attempt++) {
            await expect(bridge.handle('connectorCall', write)).resolves.not.toHaveProperty('approval_token')
        }

        expect(confirmPostHogWrite).toHaveBeenCalledTimes(2)
        expect(confirmPostHogWrite).toHaveBeenCalledWith({
            tool: write.tool,
            title: pendingWrite.confirmation.title,
            destructive: false,
            arguments: write.arguments,
        })
        expect(jest.mocked(canvasesConnectorsCall).mock.calls.map(([, , body]) => body.approval_token)).toEqual([
            undefined,
            'approval-token',
            undefined,
            'approval-token',
        ])
    })

    test('a successful write makes the next read fresh', async () => {
        jest.mocked(canvasesConnectorsCall).mockImplementation(async (_project, _canvas, body) =>
            body.tool === write.tool && !body.approval_token ? pendingWrite : okResult
        )
        const { bridge } = setup()

        await bridge.handle('connectorCall', read)
        await bridge.handle('connectorCall', read)
        expect(canvasesConnectorsCall).toHaveBeenCalledTimes(1)
        await bridge.handle('connectorCall', write)
        await bridge.handle('connectorCall', read)

        expect(canvasesConnectorsCall).toHaveBeenCalledTimes(4)
    })

    test.each([
        { name: 'without a user action', hasUserActivation: false, confirm: true, error: 'user action' },
        { name: 'when the viewer cancels', hasUserActivation: true, confirm: false, error: 'Change canceled' },
    ])('a write is not sent $name', async ({ hasUserActivation, confirm, error }) => {
        jest.mocked(canvasesConnectorsCall).mockResolvedValue(pendingWrite)
        const { bridge } = setup({ hasUserActivation, confirm })

        await expect(bridge.handle('connectorCall', write)).rejects.toThrow(error)

        expect(canvasesConnectorsCall).toHaveBeenCalledTimes(1)
        expect(jest.mocked(canvasesConnectorsCall).mock.calls[0][2]).not.toHaveProperty('approval_token')
    })
})
