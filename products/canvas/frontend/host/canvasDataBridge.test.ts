import { canvasesActionsInvoke, canvasesActionsRetrieve } from '../generated/api'
import { CanvasDataBridge } from './canvasDataBridge'

jest.mock('../generated/api')

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
