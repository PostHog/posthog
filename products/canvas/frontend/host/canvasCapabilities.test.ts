import type { CanvasCapabilitiesApi } from '../generated/api.schemas'
import { assertCanvasCapability } from './canvasCapabilities'

const capabilities: CanvasCapabilitiesApi = {
    posthog: {
        insights: ['abc123'],
        inlineQueries: false,
        captureEvents: ['canvas clicked'],
        state: ['user'],
        actions: ['annotations.create'],
        agentRequests: false,
    },
    network: { origins: [] },
    connectors: [{ provider: 'github', tools: ['list_pull_requests'] }],
}

describe('assertCanvasCapability', () => {
    test.each([
        ['query', {}, 'Inline queries are not allowed by this canvas'],
        ['loadInsight', { shortId: 'abc123' }, null],
        ['loadInsight', { shortId: 'other' }, 'Insight is not allowed by this canvas'],
        ['capture', { event: 'canvas clicked' }, null],
        ['capture', { event: '$pageview' }, 'Event capture is not allowed by this canvas'],
        ['stateGet', { key: 'k', scope: 'user' }, null],
        ['stateSet', { key: 'k', scope: 'shared' }, 'State scope "shared" is not allowed by this canvas'],
        ['stateList', {}, 'State scope "any" is not allowed by this canvas'],
        ['actionInvoke', { verb: 'annotations.create' }, null],
        ['actionInvoke', { verb: 'flags.delete' }, 'Action "flags.delete" is not allowed by this canvas'],
        ['agentRequest', { prompt: 'x' }, 'Agent requests are not allowed by this canvas'],
        ['connectorCall', { provider: 'github', tool: 'list_pull_requests' }, null],
        [
            'connectorCall',
            { provider: 'github', tool: 'merge_pull_request' },
            'Connector tool "github/merge_pull_request" is not allowed by this canvas',
        ],
        ['run', {}, 'Method "run" is not allowed by this canvas'],
    ])('%s with %j', (method, payload, error) => {
        const check = (): void => assertCanvasCapability(capabilities, method, payload)
        if (error) {
            expect(check).toThrow(error)
        } else {
            expect(check).not.toThrow()
        }
    })

    test.each(['stateGet', 'stateSet'])('defaults %s to user scope', (method) => {
        expect(() =>
            assertCanvasCapability(
                { ...capabilities, posthog: { ...capabilities.posthog, state: ['shared'] } },
                method,
                {}
            )
        ).toThrow('State scope "user" is not allowed')
    })

    test('a build without a manifest denies everything', () => {
        expect(() => assertCanvasCapability(undefined, 'loadInsight', { shortId: 'abc123' })).toThrow(
            'Canvas capability manifest is unavailable'
        )
    })
})
