import type { GenUIFrameApi } from 'products/notebooks/frontend/generated/api.schemas'

import { createGenUIHostMessageRouter, readGenUIFrame } from './genUIArtifactBridge'

const frame: GenUIFrameApi = {
    name: 'pandas_df',
    columns: [{ name: 'lat', type: 'float64' }],
    rows: [[51.5]],
    totalRowCount: 1,
    includedRowCount: 1,
    truncated: false,
}

describe('genUIArtifactBridge', () => {
    it('serves only dataframes declared by the artifact and the notebook node', async () => {
        const loadFrame = jest.fn().mockResolvedValue(frame)
        const capabilities = { notebook: { frames: ['pandas_df', 'missing_df'] } }

        await expect(readGenUIFrame(capabilities, loadFrame, { name: 'pandas_df' })).resolves.toBe(frame)
        await expect(readGenUIFrame(capabilities, loadFrame, { name: 'private_df' })).rejects.toThrow(
            'Dataframe "private_df" is not allowed'
        )
        expect(loadFrame).toHaveBeenCalledTimes(1)
    })

    it('returns a bounded error response for unsupported artifact requests', async () => {
        const responses: Record<string, unknown>[] = []
        const route = createGenUIHostMessageRouter(
            (message) => responses.push(message),
            () => ({
                onDataRequest: (method) => {
                    throw new Error(`Unsupported method: ${method}`)
                },
            })
        )

        await route({
            channel: 'posthog-canvas',
            type: 'data-request',
            id: 'request-1',
            method: 'query',
            payload: {},
        })

        expect(responses).toEqual([
            {
                channel: 'posthog-canvas',
                type: 'data-response',
                id: 'request-1',
                ok: false,
                error: 'Unsupported method: query',
            },
        ])
    })

    it('returns after the timeout when a frame request never finishes', async () => {
        jest.useFakeTimers()
        const responses: Record<string, unknown>[] = []
        const route = createGenUIHostMessageRouter(
            (message) => responses.push(message),
            () => ({ onDataRequest: () => new Promise(() => undefined) })
        )

        const routing = route({
            channel: 'posthog-canvas',
            type: 'data-request',
            id: 'request-1',
            method: 'readFrame',
            payload: { name: 'pandas_df' },
        })
        await jest.advanceTimersByTimeAsync(30_000)
        await routing

        expect(responses).toEqual([
            {
                channel: 'posthog-canvas',
                type: 'data-response',
                id: 'request-1',
                ok: false,
                error: 'Visualization data request timed out',
            },
        ])
        jest.useRealTimers()
    })
})
