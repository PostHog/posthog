import { buildHogFunctionConfigDiff, buildHogFunctionDraftDiff } from './hogFunctionConfigDiffUtils'

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

    it('redacts per-mapping secret inputs on the current side of a mappings diff', () => {
        const current = {
            mappings: [
                {
                    name: 'Slack channel',
                    inputs: { webhook_token: { value: 'xoxb-mapping-secret' } },
                    inputs_schema: [{ key: 'webhook_token', type: 'string', secret: true }],
                },
            ],
        }
        const proposed = { mappings: [] }
        const diffs = buildHogFunctionConfigDiff(current, proposed)
        expect(diffs).toHaveLength(1)
        expect(diffs[0].status).toBe('removed')
        expect(diffs[0].currentText).not.toContain('xoxb-mapping-secret')
        expect(diffs[0].currentText).toContain('[secret]')
    })

    it('compares a staged draft with the live config, ignoring compiled values and masked secrets', () => {
        const inputsSchema = [
            { key: 'url', type: 'string' },
            { key: 'token', type: 'string', secret: true },
        ]
        const live = {
            hog: 'return event',
            inputs_schema: inputsSchema,
            inputs: { url: { value: 'https://old', bytecode: ['_H', 1], order: 0 }, token: { secret: true } },
            filters: { events: [{ id: '$pageview' }], bytecode: ['_H', 1, 32] },
            mappings: null,
            masking: null,
        }
        const draft = {
            hog: 'return event',
            inputs_schema: inputsSchema,
            inputs: { url: { value: 'https://new', bytecode: ['_H', 2] }, token: { secret: true } },
            filters: { events: [{ id: '$pageview' }], bytecode: ['_H', 1, 99], bytecode_error: null },
            mappings: null,
            masking: null,
        }
        const diffs = buildHogFunctionDraftDiff(live, draft)
        expect(diffs.map((diff) => diff.field)).toEqual(['inputs'])
        expect(diffs[0].currentText).toContain('https://old')
        expect(diffs[0].proposedText).toContain('https://new')
    })

    it('shows a draft change that only touches input templating or a nested value key', () => {
        const live = {
            inputs: {
                body: { value: '{event.event}', templating: 'hog' },
                payload: { value: { value: 'a' } },
            },
        }
        const draft = {
            inputs: {
                body: { value: '{event.event}', templating: 'liquid' },
                payload: { value: { value: 'b' } },
            },
        }
        const diffs = buildHogFunctionDraftDiff(live, draft)
        expect(diffs.map((diff) => diff.field)).toEqual(['inputs'])
        expect(diffs[0].proposedText).toContain('liquid')
        expect(diffs[0].proposedText).toContain('"b"')
    })

    it('treats a missing input templating as hog, so a values-only agent edit adds no noise', () => {
        const live = { inputs: { url: { value: 'https://x', templating: 'hog' } } }
        const draft = { inputs: { url: { value: 'https://x' } } }
        expect(buildHogFunctionDraftDiff(live, draft)).toEqual([])
    })
})
