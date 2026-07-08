import { buildHogFunctionConfigDiff } from './hogFunctionConfigDiff'

describe('buildHogFunctionConfigDiff', () => {
    it('classifies each proposed field as added / removed / changed and drops unchanged ones', () => {
        const current = {
            name: 'Old name',
            hog: 'return event',
            filters: {},
            enabled: true,
            masking: { hash: 'all', ttl: 60 },
            inputs_schema: [{ key: 'url', type: 'string' }],
        }
        const proposed = {
            name: 'New name', // changed
            hog: 'return event', // unchanged → dropped
            filters: { events: [{ id: '$pageview' }] }, // empty → set = added
            enabled: false, // changed
            masking: null, // set → empty = removed
            inputs_schema: [{ key: 'url', type: 'string' }], // unchanged → dropped
        }
        const byField = Object.fromEntries(
            buildHogFunctionConfigDiff(current, proposed).map((diff) => [diff.field, diff.status])
        )
        expect(byField).toEqual({ name: 'changed', filters: 'added', enabled: 'changed', masking: 'removed' })
    })

    it('ignores server-only input noise so an unchanged input value is not a spurious change', () => {
        const current = { inputs: { url: { value: 'https://x', bytecode: ['_H', 1], order: 0 } } }
        const proposed = { inputs: { url: { value: 'https://x' } } }
        expect(buildHogFunctionConfigDiff(current, proposed)).toEqual([])
    })

    it('never exposes a current secret input value while still surfacing the change', () => {
        const current = {
            inputs: { api_key: { value: 'sk-live-supersecret' } },
            inputs_schema: [{ key: 'api_key', type: 'string', secret: true }],
        }
        const proposed = { inputs: { api_key: { value: 'sk-live-agent-proposed' } } }
        const diffs = buildHogFunctionConfigDiff(current, proposed)
        expect(diffs).toHaveLength(1)
        expect(diffs[0].status).toBe('changed')
        expect(diffs[0].currentText).not.toContain('sk-live-supersecret')
        expect(diffs[0].currentText).toContain('[secret]')
        expect(diffs[0].proposedText).toContain('sk-live-agent-proposed')
    })
})
