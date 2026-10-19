import { CANVAS_CHANNEL, canvasEditMessageSchema } from './canvasProtocol'

describe('canvas edit messages', () => {
    test.each([
        { type: 'canvas-edit-pointer', x: Infinity, y: 0 },
        { type: 'canvas-edit-root', rev: 1.5, root: null },
        { type: 'canvas-edit-root', rev: 1, root: { file: 'src/canvas.tsx', start: 20, end: 10 } },
        { type: 'canvas-edit-key', key: 'Delete', metaKey: 'false', ctrlKey: false, shiftKey: false },
        { type: 'canvas-edit-text', element: null, text: 'forged' },
    ])('rejects malformed $type messages', (message) => {
        expect(canvasEditMessageSchema.safeParse({ channel: CANVAS_CHANNEL, ...message }).success).toBe(false)
    })
})
