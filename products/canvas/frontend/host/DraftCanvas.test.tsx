import { render, waitFor } from '@testing-library/react'

import type { CanvasCapabilitiesApi } from '../generated/api.schemas'
import { CanvasDocumentBridge } from './canvasDocumentBridge'
import { DraftCanvas } from './DraftCanvas'

jest.mock('./canvasDocumentBridge', () => ({
    CanvasDocumentBridge: jest.fn().mockImplementation(() => ({ post: jest.fn(), close: jest.fn() })),
}))

const capabilities: CanvasCapabilitiesApi = {
    posthog: { insights: [], inlineQueries: false, captureEvents: [] },
    network: { origins: [] },
}

describe('DraftCanvas capabilities', () => {
    test.each([null, capabilities, { ...capabilities, posthog: { ...capabilities.posthog, inlineQueries: true } }])(
        'only forwards declared query requests with manifest %j',
        async (manifest) => {
            jest.mocked(CanvasDocumentBridge).mockClear()
            const onDataRequest = jest.fn(async () => ({ results: [] }))
            render(
                <DraftCanvas
                    documentUrl="https://example.com/sandbox"
                    capabilities={manifest}
                    files={{ 'src/canvas.tsx': 'export default function Canvas() { return null }' }}
                    entry="src/canvas.tsx"
                    theme="light"
                    commentHighlights={[]}
                    clearTextSelectionKey={0}
                    hasUserActivation={() => false}
                    onOpenExternal={jest.fn()}
                    onDataRequest={onDataRequest}
                />
            )
            const onMessage = jest.mocked(CanvasDocumentBridge).mock.calls[0][1]
            const bridge = jest.mocked(CanvasDocumentBridge).mock.results[0].value
            onMessage({ channel: 'posthog-canvas', type: 'data-request', id: 'q1', method: 'query', payload: {} })

            const allowed = manifest?.posthog.inlineQueries === true
            await waitFor(() =>
                expect(bridge.post).toHaveBeenCalledWith(expect.objectContaining({ id: 'q1', ok: allowed }))
            )
            expect(onDataRequest).toHaveBeenCalledTimes(allowed ? 1 : 0)
        }
    )
})
