import type { GenUIFrameApi } from 'products/notebooks/frontend/generated/api.schemas'

import { NOTEBOOK_FRAME_KEY_PREFIX, createGenUIHostMessageRouter, readGenUIFrame } from './genUIArtifactBridge'

const frame: GenUIFrameApi = {
    name: 'pandas_df',
    columns: [{ name: 'lat', type: 'float64' }],
    rows: [[51.5]],
    totalRowCount: 1,
    includedRowCount: 1,
    truncated: false,
}

describe('genUIArtifactBridge', () => {
    it('serves only dataframes allowed by the notebook node', async () => {
        const loadFrame = jest.fn().mockResolvedValue(frame)

        await expect(
            readGenUIFrame(['pandas_df'], loadFrame, { key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df` })
        ).resolves.toBe(frame)
        await expect(
            readGenUIFrame(['pandas_df'], loadFrame, { key: `${NOTEBOOK_FRAME_KEY_PREFIX}private_df` })
        ).rejects.toThrow('not available')
        expect(loadFrame).toHaveBeenCalledTimes(1)
    })

    it('rejects Canvas methods other than the frame shim', async () => {
        const responses: Record<string, unknown>[] = []
        const route = createGenUIHostMessageRouter(
            (message) => responses.push(message),
            () => ({ onDataRequest: jest.fn() })
        )

        await route({ channel: 'posthog-canvas', type: 'data-request', id: '1', method: 'query', payload: {} })

        expect(responses[0]).toMatchObject({ id: '1', ok: false })
    })

    it('bounds requests that never finish', async () => {
        jest.useFakeTimers()
        const responses: Record<string, unknown>[] = []
        const route = createGenUIHostMessageRouter(
            (message) => responses.push(message),
            () => ({ onDataRequest: () => new Promise(() => undefined) })
        )

        const routing = route({
            channel: 'posthog-canvas',
            type: 'data-request',
            id: '1',
            method: 'stateGet',
            payload: { key: `${NOTEBOOK_FRAME_KEY_PREFIX}pandas_df` },
        })
        await jest.advanceTimersByTimeAsync(30_000)
        await routing

        expect(responses[0]).toMatchObject({ id: '1', ok: false, error: 'Visualization data request timed out' })
        jest.useRealTimers()
    })
})
