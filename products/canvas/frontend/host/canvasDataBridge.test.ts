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

    test.each([
        { query: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: '$pageview' }] } },
        { query: { kind: 'HogQLQuery', query: 'SELECT 1' } },
        { hogql: 'SELECT 1' },
    ])('runs a supported query: %j', async (input) => {
        await expect(bridge().handle('query', input)).resolves.toEqual({ results: [], columns: [] })
        expect(api.query).toHaveBeenCalledWith(input.query ?? { kind: 'HogQLQuery', query: input.hogql }, {
            refresh: 'blocking',
        })
    })
})

describe('CanvasDataBridge action confirmation', () => {
    test('invokes a plain write without asking the viewer', async () => {
        const action = {
            verb: 'annotations.create',
            summary: 'Create an annotation.',
            destructive: false,
            starts_cloud_run: false,
            usage: '',
        }
        const payload = { content: 'Deployed' }
        jest.mocked(canvasesActionsRetrieve).mockResolvedValue({ actions: [action] })
        jest.mocked(canvasesActionsInvoke)
            .mockReset()
            .mockResolvedValue({ verb: action.verb, result: { annotation_id: 1 } })
        const confirmAction = jest.fn(async () => false)
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

        await expect(bridge.handle('actionInvoke', { verb: action.verb, payload })).resolves.toEqual({
            verb: action.verb,
            result: { annotation_id: 1 },
        })
        expect(confirmAction).not.toHaveBeenCalled()
    })

    test.each([false, true])('only starts a paid task after approval: %s', async (allowed) => {
        const action = {
            verb: 'tasks.create_and_run',
            summary: 'Start a cloud task.',
            destructive: false,
            starts_cloud_run: true,
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
