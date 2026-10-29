import { PAGE_AGENT_REPLY_SOURCE, PageAgentReply, PageAgentRequestMessage } from './pageAgentProtocol'
import { PageFlagMutationStatus, PagePosthogBridge } from './pagePosthogBridge'
import type { PageAnalyticsInfo } from './pageToolbarBridge'

const INFO: PageAnalyticsInfo = {
    version: '1.300.0',
    scrollPropertiesDisabled: false,
    scrollRootSelector: null,
    heatmapsEnabled: true,
    webVitalsEnabled: true,
    webExperimentsDisabled: false,
    sessionRecordingConfig: {},
    sessionRecordingStatus: null,
    featureFlags: { overrides: {}, variants: { 'launch-banner': false }, groups: {} },
}

function reply(message: PageAgentReply): void {
    window.dispatchEvent(
        new MessageEvent('message', { data: { source: PAGE_AGENT_REPLY_SOURCE, reply: message }, source: window })
    )
}

describe('PagePosthogBridge', () => {
    let bridge: PagePosthogBridge
    let statuses: PageFlagMutationStatus[]
    let requests: PageAgentRequestMessage[]

    beforeEach(() => {
        statuses = []
        requests = []
        jest.spyOn(window, 'postMessage').mockImplementation((message: unknown) => {
            requests.push(message as PageAgentRequestMessage)
        })
        bridge = new PagePosthogBridge(INFO, (status) => statuses.push(status))
    })

    afterEach(() => {
        bridge.dispose()
        jest.restoreAllMocks()
    })

    it('reports a new override synchronously, before the page agent answers', () => {
        bridge.posthog.featureFlags.overrideFeatureFlags({ flags: { 'launch-banner': true } })

        expect(bridge.posthog.get_property('$override_feature_flags')).toEqual({ 'launch-banner': true })
        expect(requests).toMatchObject([{ request: { method: 'override-flags', flags: { 'launch-banner': true } } }])
        expect(statuses.at(-1)).toEqual({ pending: true, error: null, revision: 0 })
    })

    it.each([
        ['a reply to its own request ends the mutation', true, { pending: false, error: null, revision: 1 }],
        ['a reply to an unknown request is ignored', false, { pending: true, error: null, revision: 0 }],
    ])('%s', (_, ownRequest, expectedStatus) => {
        bridge.posthog.featureFlags.overrideFeatureFlags({ flags: { 'launch-banner': true } })
        const id = ownRequest ? requests[0].id : requests[0].id + 100

        reply({
            kind: 'result',
            id,
            ok: true,
            featureFlags: { ...INFO.featureFlags, overrides: { 'launch-banner': true } },
        })

        expect(statuses.at(-1)).toEqual(expectedStatus)
    })

    it("fails a change the page agent never answers, so the panel's controls come back", () => {
        jest.useFakeTimers()
        bridge.posthog.featureFlags.overrideFeatureFlags({ flags: { 'launch-banner': true } })

        jest.runOnlyPendingTimers()

        expect(statuses.at(-1)).toEqual({ pending: false, error: "The page didn't answer.", revision: 1 })
        jest.useRealTimers()
    })

    it('keeps the error the page agent reports', () => {
        bridge.posthog.featureFlags.overrideFeatureFlags(false)

        reply({ kind: 'result', id: requests[0].id, ok: false, error: 'The page has no posthog-js' })

        expect(statuses.at(-1)).toEqual({ pending: false, error: 'The page has no posthog-js', revision: 1 })
        expect(bridge.posthog.get_property('$override_feature_flags')).toEqual({})
    })

    it('ends a debug info request when the page has no posthog-js to answer it', async () => {
        const debugInfo = bridge.readDebugInfo()

        reply({ kind: 'result', id: requests[0].id, ok: false, error: 'The page has no posthog-js' })

        await expect(debugInfo).resolves.toBeNull()
    })

    it("subscribes once to the page's events and gives each one to every listener", () => {
        const debuggerEvents: unknown[] = []
        const webVitalsEvents: unknown[] = []
        bridge.posthog.on('eventCaptured', (event) => debuggerEvents.push(event))
        bridge.posthog.on('eventCaptured', (event) => webVitalsEvents.push(event))

        reply({ kind: 'event-captured', event: { event: '$pageview' } })

        expect(requests.map(({ request }) => request.method)).toEqual(['subscribe-events'])
        expect(debuggerEvents).toEqual([{ event: '$pageview' }])
        expect(webVitalsEvents).toEqual([{ event: '$pageview' }])
    })
})
