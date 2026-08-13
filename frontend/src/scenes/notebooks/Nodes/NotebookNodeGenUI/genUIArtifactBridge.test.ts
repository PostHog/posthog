import { createGenUIHostMessageRouter, readGenUIFrame } from './genUIArtifactBridge'
import type { GenUIFrame } from './genUIFrames'

const frame: GenUIFrame = {
    name: 'pandas_df',
    columns: [{ name: 'lat', type: 'float64' }],
    rows: [[51.5]],
    totalRowCount: 1,
    includedRowCount: 1,
    truncated: false,
}

describe('genUIArtifactBridge', () => {
    it('serves only dataframes declared by the artifact and the notebook node', () => {
        const frames = { pandas_df: frame, private_df: { ...frame, name: 'private_df' } }
        const capabilities = { notebook: { frames: ['pandas_df', 'missing_df'] } }

        expect(readGenUIFrame(capabilities, frames, { name: 'pandas_df' })).toBe(frame)
        expect(() => readGenUIFrame(capabilities, frames, { name: 'private_df' })).toThrow(
            'Dataframe "private_df" is not allowed'
        )
        expect(() => readGenUIFrame(capabilities, frames, { name: 'missing_df' })).toThrow(
            'Dataframe "missing_df" is unavailable'
        )
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
})
