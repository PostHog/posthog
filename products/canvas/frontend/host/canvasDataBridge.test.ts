import api from 'lib/api'

import { canvasesActionsInvoke, canvasesActionsRetrieve } from '../generated/api'
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
