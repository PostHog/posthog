import { buildGenUIGenerationPrompt } from './genUIGenerationPrompt'

describe('buildGenUIGenerationPrompt', () => {
    it('routes canvas operations through the PostHog exec tool', () => {
        const prompt = buildGenUIGenerationPrompt({
            canvasId: 'canvas-123',
            name: 'Spinning globe',
            instruction: 'Render a spinning 3D globe.',
            frames: [],
            missingFrames: [],
            isEdit: false,
        })

        expect(prompt).toContain('mcp__posthog__exec')
        expect(prompt).toContain('command: call canvas-source-retrieve {"id":"canvas-123"}')
        expect(prompt).toContain('call canvas-validate-create')
        expect(prompt).toContain('call canvas-publish-create')
        expect(prompt).toContain('call canvas-builds-retrieve')
        expect(prompt).toContain('Do not use `ToolSearch`')
        expect(prompt).not.toContain('channel "')
    })

    it('includes the notebook frame contract', () => {
        const prompt = buildGenUIGenerationPrompt({
            canvasId: 'canvas-123',
            name: 'Spinning globe',
            instruction: 'Plot each location.',
            frames: [
                {
                    name: 'pandas_df',
                    columns: [
                        { name: 'lat', type: 'float64' },
                        { name: 'lng', type: 'float64' },
                    ],
                    totalRowCount: 8,
                    includedRowCount: 8,
                    truncated: false,
                },
            ],
            missingFrames: [],
            isEdit: true,
        })

        expect(prompt).toContain('Read notebook data only with `await ph.readFrame(name)`')
        expect(prompt).toContain('"name":"pandas_df"')
        expect(prompt).toContain('"name":"lat","type":"float64"')
        expect(prompt).toContain('Update the existing canvas')
    })
})
