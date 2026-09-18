import posthog, { BeforeSendFn, CaptureResult } from 'posthog-js'
import { PostHog } from 'posthog-js/lib/src/posthog-core'

import { loadPostHogJS, LoadPostHogJSOptions } from '../../loadPostHogJS'
import { createCustomerJourney, CustomerJourneyContext } from './createCustomerJourney'
import { projectCustomerJourneyCapture } from './projectCustomerJourneyCapture'

const context: CustomerJourneyContext = {
    journey_name: 'dashboard_refresh',
    resource_type: 'dashboard',
    resource_id: 42,
    trigger: 'manual_refresh',
    readiness_contract_version: 1,
    readiness_scope: 'visible_product_analytics_tiles',
    attempt_id: 'synthetic-attempt',
    region: 'US',
    project_id: 101,
    organization_id: 'synthetic-organization',
    registry_version: 'test-v1',
    workload_class: 'unknown',
}

function coreEvents(): CaptureResult[] {
    const events: CaptureResult[] = []
    let time = 0
    const journey = createCustomerJourney(context, {
        now: () => time,
        capture: (event, properties) => {
            events.push({ uuid: '01995a00-0000-7000-8000-000000000001', event, properties })
        },
        visibility: { getState: () => 'visible', subscribe: () => () => {} },
    })!
    time = 10
    journey.firstUseful()
    time = 20
    journey.finish('failed', {
        error_type: 'query_error',
        end_reason: 'exited',
        exposures_response_cached: true,
        total_count: 3,
        ready_count: 1,
        failed_count: 1,
        pending_count: 1,
        excluded_count: 2,
        insight_type_summary: { TRENDS: { total_count: 3, ready_count: 1, failed_count: 1, max_duration_ms: 10 } },
        tile_results: [
            { tile_id: 1, insight_short_id: 'abc', insight_type: 'TRENDS', state: 'ready', duration_ms: 10 },
            { tile_id: 2, insight_short_id: 'def', insight_type: 'TRENDS', state: 'failed' },
            { tile_id: 3, insight_short_id: 'ghi', insight_type: 'TRENDS', state: 'pending' },
        ],
        tile_results_truncated: true,
    })
    return events
}

function configuredHooks(beforeSend?: LoadPostHogJSOptions['beforeSend']): BeforeSendFn[] {
    window.JS_POSTHOG_API_KEY = 'synthetic-token'
    jest.mocked(posthog.get_session_id).mockReturnValue('synthetic-session')
    loadPostHogJS({ beforeSend })
    const calls = jest.mocked(posthog.init).mock.calls
    return calls[calls.length - 1][1]!.before_send as BeforeSendFn[]
}

function syntheticClient(beforeSend?: LoadPostHogJSOptions['beforeSend']): {
    client: PostHog
    send: jest.SpyInstance
} {
    const hooks = configuredHooks(beforeSend)
    const calls = jest.mocked(posthog.init).mock.calls
    const appConfig = calls[calls.length - 1][1]!
    const client = new PostHog()
    // Stop only transport; capture, persistence, session and initial attribution use the installed SDK.
    const send = jest.spyOn(client, '_send_retriable_request').mockImplementation(() => {})
    jest.spyOn(client, '_send_request').mockImplementation(() => {})
    client.init('synthetic-token', {
        ...appConfig,
        before_send: hooks,
        loaded: () => {},
        __extensionClasses: undefined,
        persistence: 'memory',
        internal_or_test_user_hostname: 'synthetic-never.test',
        opt_out_useragent_filter: true,
        opt_out_capturing_by_default: false,
        capture_pageview: false,
        capture_pageleave: false,
        autocapture: false,
        disable_session_recording: true,
        disable_surveys: true,
        disable_external_dependency_loading: true,
        advanced_disable_flags: true,
        request_batching: false,
        __preview_deferred_init_extensions: false,
        bootstrap: { distinctID: 'synthetic-person', isIdentifiedID: true },
        metrics: { network: false },
    })
    client.register({
        $device_id: 'synthetic-device',
        $user_id: 'synthetic-person',
        $groups: { organization: 'org-1' },
    })
    return { client, send }
}

describe('journey outbound SDK projection', () => {
    const originalKey = window.JS_POSTHOG_API_KEY

    beforeEach(() => {
        jest.useFakeTimers()
        window.history.replaceState(
            {},
            '',
            '/project/101/sql#q=synthetic-sql-secret&search=synthetic-search-secret&filter=synthetic-filter-secret'
        )
    })

    afterEach(() => {
        jest.clearAllTimers()
        jest.useRealTimers()
        jest.restoreAllMocks()
        window.JS_POSTHOG_API_KEY = originalKey
        window.history.replaceState({}, '', '/')
    })

    it('preserves every current core output field while projecting nested metadata and envelope profile updates', () => {
        for (const event of coreEvents()) {
            const enriched = {
                ...event,
                $set: { private: 'secret' },
                $set_once: { $initial_current_url: 'secret' },
                $unset: ['secret'],
                properties: { ...event.properties, $current_url: 'secret', $set: { private: 'secret' } },
            }
            expect(projectCustomerJourneyCapture(enriched)).toEqual(event)
        }
        const event = coreEvents()[1]
        event.properties.tile_results[0].query = 'secret'
        event.properties.insight_type_summary.TRENDS.raw_error = 'secret'
        expect(JSON.stringify(projectCustomerJourneyCapture(event))).not.toContain('secret')
    })

    it.each([
        null,
        [],
        { schema_version: 1, attempt_id: 'a', tile_results: {} },
        { schema_version: 1, attempt_id: 'a', resource_id: { query: 'secret' } },
    ])('fails closed for malformed journey properties %p', (properties) => {
        expect(projectCustomerJourneyCapture({ ...coreEvents()[0], properties } as CaptureResult)).toBeNull()
    })

    it('leaves unrelated events and caller drops untouched', () => {
        const event = { ...coreEvents()[0], event: 'normal', $set_once: { url: 'secret' } }
        expect(projectCustomerJourneyCapture(event)).toBe(event)
        expect(projectCustomerJourneyCapture(null)).toBeNull()
        const throwing = {
            ...coreEvents()[0],
            properties: new Proxy(
                {},
                {
                    get: () => {
                        throw new Error('broken')
                    },
                }
            ),
        }
        expect(() => projectCustomerJourneyCapture(throwing)).not.toThrow()
        expect(projectCustomerJourneyCapture(throwing)).toBeNull()
    })

    it.each(['none', 'function', 'array'] as const)('filters actual SDK enrichment after %s caller hooks', (mode) => {
        const enriched: CaptureResult[] = []
        const hook = jest.fn((event: CaptureResult | null) => {
            if (event) {
                enriched.push(event)
                return { ...event, properties: { ...event.properties, caller_secret: 'synthetic-caller-secret' } }
            }
            return event
        })
        const hooks = mode === 'none' ? undefined : mode === 'function' ? hook : [hook, hook]
        const { client, send } = syntheticClient(hooks)
        client.register({ arbitrary: 'synthetic-superproperty-secret' })
        client.register_for_session({ arbitrary_session: 'synthetic-session-secret' })
        const events = coreEvents()
        const captured: CaptureResult[] = []
        const timestamp = new Date('2026-09-18T01:00:00Z')
        for (const event of events) {
            const result = client.capture(event.event, event.properties, {
                uuid: event.uuid,
                timestamp,
                $set: { profile: 'synthetic-profile-secret' },
                $set_once: { initial: 'synthetic-initial-secret' },
                $unset: ['synthetic-unset-secret'],
            })!
            expect(result).not.toBeUndefined()
            captured.push(result)
            expect(result.uuid).toBe(event.uuid)
            expect(result.timestamp).toEqual(timestamp)
            expect(result.properties).toMatchObject({
                ...event.properties,
                token: 'synthetic-token',
                distinct_id: 'synthetic-person',
                $device_id: 'synthetic-device',
                $user_id: 'synthetic-person',
                $session_id: expect.any(String),
                $window_id: expect.any(String),
                $groups: { organization: 'org-1' },
                $is_identified: true,
                $process_person_profile: true,
                $event_time_override_provided: true,
                $event_time_override_system_time: expect.any(Date),
            })
            expect(JSON.stringify(result)).not.toContain('secret')
            expect(send.mock.calls.at(-1)![0].data).toEqual(result)
            if (event.event === 'customer_journey_started') {
                client.capture('$pageview')
            }
        }
        expect(captured[1].properties.$pageview_id).toEqual(expect.any(String))
        const firstJourney = enriched.find((event) => event.event === 'customer_journey_started')
        expect(firstJourney?.properties.$current_url ?? '').toContain(mode === 'none' ? '' : 'synthetic-sql-secret')
        expect(firstJourney?.properties.$session_entry_url ?? '').toContain(
            mode === 'none' ? '' : 'synthetic-search-secret'
        )
        expect(firstJourney?.$set_once?.$initial_current_url ?? '').toContain(
            mode === 'none' ? '' : 'synthetic-filter-secret'
        )
        expect(firstJourney?.properties.arbitrary).toBe(mode === 'none' ? undefined : 'synthetic-superproperty-secret')
        const normal = client.capture('normal-event', { ordinary: true })!
        expect(normal.properties.$current_url).toContain('synthetic-sql-secret')
        expect(normal.properties.arbitrary).toBe('synthetic-superproperty-secret')
        expect(normal.properties.ordinary).toBe(true)
        expect(normal.properties.caller_secret).toBe(mode === 'none' ? undefined : 'synthetic-caller-secret')
        // The SDK marks initial attribution sent before before_send. We intentionally do not rewind it.
        expect(normal.$set_once).toBeUndefined()
    })

    it.each(['function', 'array'] as const)('preserves caller drop behavior with a %s hook', (mode) => {
        const drop: BeforeSendFn = () => null
        const afterDrop = jest.fn((event) => event)
        const { client, send } = syntheticClient(mode === 'function' ? drop : [drop, afterDrop])
        send.mockClear()
        const event = coreEvents()[0]
        expect(client.capture(event.event, event.properties)).toBeUndefined()
        expect(client.capture('normal-event')).toBeUndefined()
        expect(afterDrop).not.toHaveBeenCalled()
        expect(send).not.toHaveBeenCalled()
    })
})
