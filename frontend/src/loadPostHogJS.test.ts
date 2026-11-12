import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import posthog, { CaptureResult, PostHog, PostHogConfig } from 'posthog-js'

import { AppContext, UserType } from '~/types'

import { LastSeenFeatureFlags, loadPostHogJS, withLastSeenFeatureFlags } from './loadPostHogJS'

describe('loadPostHogJS', () => {
    describe('user identity groups', () => {
        let sdk: PostHog
        let events: CaptureResult[]
        let identifyUser: typeof import('./lib/utils/posthogIdentity').identifyUserInPostHog

        const user: UserType = {
            ...MOCK_DEFAULT_USER,
            distinct_id: 'new-user',
            email: 'new-user@example.com',
            team: { ...MOCK_DEFAULT_TEAM, id: 2, uuid: 'new-project', name: 'New project' },
            organization: {
                ...MOCK_DEFAULT_ORGANIZATION,
                id: 'new-org',
                name: 'New organization',
                teams: [],
                customer_id: 'new-customer',
            },
        }

        beforeEach(() => {
            jest.useFakeTimers()
            jest.isolateModules(() => {
                identifyUser = require('./lib/utils/posthogIdentity').identifyUserInPostHog
            })
            events = []
            sdk = new PostHog()
            sdk.init('phc_example_identity', {
                persistence: 'memory',
                bootstrap: { distinctID: 'previous-user', isIdentifiedID: true },
                advanced_disable_flags: true,
                autocapture: false,
                capture_pageview: false,
                capture_pageleave: false,
                disable_session_recording: true,
                disable_surveys: true,
                disable_external_dependency_loading: true,
                before_send: (event) => {
                    if (event) {
                        events.push(event)
                    }
                    return null
                },
            })
            sdk.identify('previous-user')
            sdk.group('instance', 'current-instance', { site_url: 'current-instance' })
            sdk.group('project', 'old-project', { previous_project_property: true })
            sdk.group('organization', 'old-org', { previous_org_property: true })
            sdk.group('customer', 'old-customer', { previous_customer_property: true })
            events.length = 0
        })

        afterEach(() => {
            jest.clearAllTimers()
            jest.useRealTimers()
        })

        it.each([
            [
                'with a customer',
                user,
                { project: 'new-project', organization: 'new-org', customer: 'new-customer' },
                false,
            ],
            [
                'without a customer',
                { ...user, organization: { ...user.organization!, customer_id: null } },
                { project: 'new-project', organization: 'new-org' },
                false,
            ],
            ['without an organization', { ...user, team: null, organization: null }, {}, false],
            [
                'from anonymous signup',
                user,
                { project: 'new-project', organization: 'new-org', customer: 'new-customer' },
                true,
            ],
        ] as const)('captures only the new groups %s', (_, nextUser, expectedGroups, anonymous) => {
            if (anonymous) {
                sdk.reset()
                sdk.group('instance', 'current-instance', { site_url: 'current-instance' })
                events.length = 0
            }
            expect(identifyUser(sdk, nextUser)).toBe(true)

            expect(events.length).toBeGreaterThan(0)
            for (const event of events) {
                expect(event.properties.distinct_id).toBe('new-user')
                expect(event.properties.$groups).toEqual({ instance: 'current-instance', ...expectedGroups })
            }
            const customerGroupKeys = events
                .filter((event) => event.event === '$groupidentify' && event.properties.$group_type === 'customer')
                .map((event) => event.properties.$group_key)
            expect(customerGroupKeys).toEqual('customer' in expectedGroups ? [expectedGroups.customer] : [])
            expect(sdk.getGroups()).toEqual({ instance: 'current-instance', ...expectedGroups })
            const flagProperties = sdk.get_property('$stored_group_properties')
            expect(flagProperties.instance).toEqual({ site_url: 'current-instance' })
            expect(flagProperties.project ?? {}).not.toHaveProperty('previous_project_property')
            expect(flagProperties.organization ?? {}).not.toHaveProperty('previous_org_property')
            expect(flagProperties.customer ?? {}).not.toHaveProperty('previous_customer_property')
        })

        it('preserves flag properties for unchanged groups and skips duplicate identities', () => {
            identifyUser(sdk, user)
            sdk.setGroupPropertiesForFlags({ organization: { retained_property: true } }, false)
            events.length = 0

            expect(identifyUser(sdk, { ...user, email: 'updated@example.com' })).toBe(true)
            expect(sdk.get_property('$stored_group_properties').organization.retained_property).toBe(true)
            expect(events.length).toBeGreaterThan(0)
            events.length = 0

            expect(identifyUser(sdk, { ...user, email: 'updated@example.com' })).toBe(false)
            expect(events).toEqual([])
        })
    })

    describe('withLastSeenFeatureFlags', () => {
        const serverFlags = { 'server-decided': false, variant: 'control' }

        it.each<{
            case: string
            lastSeen: LastSeenFeatureFlags | null
            bootstrapFlags: LastSeenFeatureFlags['featureFlags'] | null | undefined
            expected: LastSeenFeatureFlags['featureFlags'] | undefined
        }>([
            {
                case: 'fills flags the server left out, and server values win',
                lastSeen: { distinctId: 'user-a', featureFlags: { 'server-decided': true, 'staff-only': true } },
                bootstrapFlags: serverFlags,
                expected: { 'server-decided': false, variant: 'control', 'staff-only': true },
            },
            {
                case: 'ignores flags another user saw on this browser',
                lastSeen: { distinctId: 'user-b', featureFlags: { 'staff-only': true } },
                bootstrapFlags: serverFlags,
                expected: serverFlags,
            },
            {
                case: 'keeps an empty bootstrap empty so posthog-js uses its own persisted flags',
                lastSeen: { distinctId: 'user-a', featureFlags: { 'staff-only': true } },
                bootstrapFlags: {},
                expected: {},
            },
            {
                case: 'keeps missing bootstrap flags absent when the same user has cached flags',
                lastSeen: { distinctId: 'user-a', featureFlags: { 'staff-only': true } },
                bootstrapFlags: undefined,
                expected: undefined,
            },
            {
                case: 'ignores null bootstrap flags when the same user has cached flags',
                lastSeen: { distinctId: 'user-a', featureFlags: { 'staff-only': true } },
                bootstrapFlags: null,
                expected: undefined,
            },
            {
                case: 'keeps the server flags when nothing is cached',
                lastSeen: null,
                bootstrapFlags: serverFlags,
                expected: serverFlags,
            },
        ])('$case', ({ lastSeen, bootstrapFlags, expected }) => {
            expect(withLastSeenFeatureFlags({ featureFlags: bootstrapFlags }, lastSeen, 'user-a').featureFlags).toEqual(
                expected
            )
        })
    })

    describe('without a project key', () => {
        it('starts posthog-js with no request to PostHog', () => {
            window.JS_POSTHOG_API_KEY = undefined

            loadPostHogJS()

            expect(posthog.init).toHaveBeenCalledWith(
                'fake_token',
                expect.objectContaining({ advanced_disable_flags: true, opt_out_capturing_by_default: true })
            )
        })
    })

    function initConfigFor(context: Partial<AppContext> | undefined, selfCapture: boolean): Partial<PostHogConfig> {
        const original = {
            key: window.JS_POSTHOG_API_KEY,
            host: window.JS_POSTHOG_HOST,
            selfCapture: window.JS_POSTHOG_SELF_CAPTURE,
            context: window.POSTHOG_APP_CONTEXT,
        }
        window.JS_POSTHOG_API_KEY = 'phc_example'
        window.JS_POSTHOG_HOST = window.location.origin
        window.JS_POSTHOG_SELF_CAPTURE = selfCapture
        window.POSTHOG_APP_CONTEXT = context as AppContext | undefined
        jest.mocked(posthog.get_session_id).mockReturnValue('example-session')
        jest.mocked(posthog.init).mockClear()
        try {
            loadPostHogJS()
            return jest.mocked(posthog.init).mock.calls[0][1] ?? {}
        } finally {
            window.JS_POSTHOG_API_KEY = original.key
            window.JS_POSTHOG_HOST = original.host
            window.JS_POSTHOG_SELF_CAPTURE = original.selfCapture
            window.POSTHOG_APP_CONTEXT = original.context
        }
    }

    it.each([
        ['hobby with self-capture', { run_mode: 'HOBBY' }, true, false],
        ['hobby with Cloud assets', { run_mode: 'HOBBY' }, false, undefined],
        ['US cloud', { run_mode: 'US' }, false, undefined],
        ['EU cloud', { run_mode: 'EU' }, false, undefined],
        ['cloud development', { run_mode: 'DEV' }, false, undefined],
        ['local development', { run_mode: 'LOCAL' }, false, undefined],
        ['E2E', { run_mode: 'E2E' }, false, undefined],
        ['older app context', {}, false, undefined],
        ['missing app context', undefined, false, undefined],
    ] as const)('selects script versioning for %s', (_, context, selfCapture, expected) => {
        const config = initConfigFor(context, selfCapture)
        if (expected === undefined) {
            expect(config).not.toHaveProperty('strict_script_versioning')
        } else {
            expect(config).toHaveProperty('strict_script_versioning', expected)
        }
    })

    it.each([
        ['$exception', true],
        ['$ai_generation', true],
        ['$ai_trace', true],
        ['$web_vitals', true],
        ['$performance', true],
        ['$snapshot', true],
        ['$pageview', false],
        ['user action', false],
    ] as const)('preserves %s capture and classifies its activity', (event, passive) => {
        const beforeSend = [initConfigFor({ run_mode: 'US' }, false).before_send ?? []].flat()
        const capture = { uuid: 'example', event, properties: { retained: true } } as CaptureResult
        const result = beforeSend.reduce<CaptureResult | null>(
            (current, filter) => (current ? filter(current) : null),
            capture
        )

        expect(result?.properties?.retained).toBe(true)
        expect(result?.properties?.$update_person_last_seen_at).toBe(passive ? false : undefined)
    })

    it.each([
        ['local development sending to Cloud', { run_mode: 'LOCAL' }, false, false],
        ['local development with self-capture', { run_mode: 'LOCAL' }, true, true],
        ['US cloud', { run_mode: 'US' }, false, true],
        ['hobby with Cloud assets', { run_mode: 'HOBBY' }, false, true],
    ] as const)('filters exceptions for %s', (_, context, selfCapture, sent) => {
        const beforeSend = [initConfigFor(context, selfCapture).before_send ?? []].flat()
        const exception = { uuid: 'example', event: '$exception', properties: {} } as CaptureResult
        const pageview = { ...exception, event: '$pageview' }

        const runFilters = (event: CaptureResult): CaptureResult | null =>
            beforeSend.reduce<CaptureResult | null>((current, filter) => (current ? filter(current) : null), event)

        expect(runFilters(exception) !== null).toBe(sent)
        expect(runFilters(pageview)).not.toBeNull()
    })
})
