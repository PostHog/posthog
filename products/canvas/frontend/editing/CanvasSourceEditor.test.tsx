import { render, waitFor } from '@testing-library/react'

import type { CanvasCapabilitiesApi } from '../generated/api.schemas'
import { CanvasDocumentBridge } from '../host/canvasDocumentBridge'
import { BLOCK_RUNTIME_PATH } from './blockLibrary/blockDefinitions'
import { CanvasSourceEditor } from './CanvasSourceEditor'
import { CanvasSourceEntry, applySourceFiles, loadSourceEntry } from './canvasSourceSnapshots'

let mockEntry: CanvasSourceEntry
jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: () => ({ entry: mockEntry }),
    useActions: () => ({}),
}))
jest.mock('./canvasEditLogic', () => ({ canvasEditLogic: {} }))
jest.mock('./SourceDragOverlay', () => ({ SourceDragOverlay: () => null }))
jest.mock('../host/canvasDocumentBridge', () => ({
    CanvasDocumentBridge: jest.fn().mockImplementation(() => ({ post: jest.fn(), close: jest.fn() })),
}))

describe('CanvasSourceEditor capabilities', () => {
    test.each(['missing', 'denied', 'allowed', 'existing blocks', 'added blocks'])(
        'enforces query permissions with %s',
        async (state) => {
            jest.mocked(CanvasDocumentBridge).mockClear()
            const capabilities: CanvasCapabilitiesApi = {
                posthog: { insights: [], inlineQueries: state === 'allowed', captureEvents: [] },
                network: { origins: [] },
            }
            mockEntry = loadSourceEntry(
                null,
                {
                    schemaVersion: 1,
                    entryHtml: 'index.html',
                    files: state === 'existing blocks' ? { [BLOCK_RUNTIME_PATH]: '' } : {},
                    capabilities: state === 'missing' ? undefined : capabilities,
                },
                'v1'
            )
            if (state === 'added blocks') {
                mockEntry = applySourceFiles(mockEntry, { [BLOCK_RUNTIME_PATH]: '' })
            }
            const onDataRequest = jest.fn(async () => ({ results: [] }))
            render(
                <CanvasSourceEditor
                    documentUrl="https://example.com/sandbox"
                    theme="light"
                    hasUserActivation={() => false}
                    onOpenExternal={jest.fn()}
                    onDataRequest={onDataRequest}
                />
            )
            const onMessage = jest.mocked(CanvasDocumentBridge).mock.calls[0][1]
            const bridge = jest.mocked(CanvasDocumentBridge).mock.results[0].value
            onMessage({ channel: 'posthog-canvas', type: 'data-request', id: 'q1', method: 'query', payload: {} })

            const allowed = state === 'allowed' || state === 'added blocks'
            await waitFor(() =>
                expect(bridge.post).toHaveBeenCalledWith(expect.objectContaining({ id: 'q1', ok: allowed }))
            )
            expect(onDataRequest).toHaveBeenCalledTimes(allowed ? 1 : 0)
        }
    )
})
