import { ErrorEventProperties, ErrorTrackingStackFrame, ExceptionAttributes } from './types'
import {
    getExceptionAttributes,
    getExceptionList,
    getExceptionRelease,
    getInstructionAddress,
    getRuntimeFromLib,
    getSessionId,
} from './utils'

describe('Error Display', () => {
    it('recognizes the Kotlin Multiplatform SDK runtime', () => {
        expect(getRuntimeFromLib('posthog-kmp')).toBe('kotlin')
    })

    it('can read sentry stack trace when $exception_list is not present', () => {
        const eventProperties = {
            'should not be in the': 'result',
            $browser: 'Chrome',
            $browser_version: '92.0.4515',
            $active_feature_flags: ['feature1,feature2'],
            $lib: 'posthog-js',
            $lib_version: '1.0.0',
            $os: 'Windows',
            $os_version: '10',
            $sentry_exception_message: 'There was an error creating the support ticket with zendesk.',
            $exception_message: 'There was an error creating the support ticket with zendesk.',
            $sentry_tags: {
                'PostHog Person URL': 'https://app.posthog.com/person/f6kW3HXaha6dAvHZiOmgrcAXK09682P6nNPxvfjqM9c',
                'PostHog Recording URL': 'https://app.posthog.com/replay/018dc30d-a8a5-7257-9faf-dcd97c0e19cf?t=2294',
            },
            $sentry_exception: {
                values: [
                    {
                        mechanism: {
                            handled: true,
                            type: 'generic',
                        },
                        stacktrace: {
                            frames: [
                                {
                                    colno: 220,
                                    filename: 'https://app-static-prod.posthog.com/static/chunk-UFQKIDIH.js',
                                    function: 'submitZendeskTicket',
                                    in_app: true,
                                    lineno: 25,
                                },
                            ],
                        },
                        type: 'Error',
                        value: 'There was an error creating the support ticket with zendesk.',
                    },
                ],
            },
            $sentry_url:
                'https://sentry.io/organizations/posthog/issues/?project=1899813&query=40e442d79c22473391aeeeba54c82163',
            $sentry_event_id: '40e442d79c22473391aeeeba54c82163',
            $sentry_exception_type: 'Error',
            $exception_personURL: 'https://app.posthog.com/person/f6kW3HXaha6dAvHZiOmgrcAXK09682P6nNPxvfjqM9c',
            $exception_type: 'Error',
        }
        const result = getExceptionList(eventProperties)
        expect(result).toEqual([
            {
                mechanism: {
                    handled: true,
                    type: 'generic',
                },
                stacktrace: {
                    frames: [
                        {
                            colno: 220,
                            filename: 'https://app-static-prod.posthog.com/static/chunk-UFQKIDIH.js',
                            function: 'submitZendeskTicket',
                            in_app: true,
                            lineno: 25,
                        },
                    ],
                },
                type: 'Error',
                value: 'There was an error creating the support ticket with zendesk.',
            },
        ])
    })

    it('can read sentry message', () => {
        const eventProperties = {
            'should not be in the': 'result',
            $browser: 'Chrome',
            $browser_version: '92.0.4515',
            $active_feature_flags: ['feature1,feature2'],
            $lib: 'posthog-js',
            $lib_version: '1.0.0',
            $os: 'Windows',
            $os_version: '10',
            $sentry_tags: {
                'PostHog Person URL': 'https://app.posthog.com/person/f6kW3HXaha6dAvHZiOmgrcAXK09682P6nNPxvfjqM9c',
                'PostHog Recording URL': 'https://app.posthog.com/replay/018dc30d-a8a5-7257-9faf-dcd97c0e19cf?t=2294',
            },
            $sentry_exception: undefined,
            $sentry_url:
                'https://sentry.io/organizations/posthog/issues/?project=1899813&query=40e442d79c22473391aeeeba54c82163',
            $sentry_event_id: '40e442d79c22473391aeeeba54c82163',
            $sentry_exception_type: undefined,
            $exception_personURL: 'https://app.posthog.com/person/f6kW3HXaha6dAvHZiOmgrcAXK09682P6nNPxvfjqM9c',
            $exception_type: undefined,
            $level: 'info',
            $exception_message: 'the message sent into sentry captureMessage',
        }
        const result = getExceptionAttributes(eventProperties)
        expect(result).toEqual({
            browser: 'Chrome',
            browserVersion: '92.0.4515',
            value: 'the message sent into sentry captureMessage',
            ingestionErrors: undefined,
            handled: false,
            synthetic: undefined,
            type: undefined,
            url: undefined,
            runtime: 'web',
            lib: 'posthog-js',
            libVersion: '1.0.0',
            level: undefined,
            os: 'Windows',
            osVersion: '10',
            sentryUrl:
                'https://sentry.io/organizations/posthog/issues/?project=1899813&query=40e442d79c22473391aeeeba54c82163',
        } as ExceptionAttributes)
    })

    it('can read exception_list stack trace when $exception_type and message are not present', () => {
        const eventProperties = {
            'should not be in the': 'result',
            $browser: 'Chrome',
            $browser_version: '92.0.4515',
            $active_feature_flags: ['feature1,feature2'],
            $lib: 'posthog-js',
            $lib_version: '1.0.0',
            $os: 'Windows',
            $os_version: '10',
            $exception_list: [
                {
                    mechanism: {
                        handled: true,
                        type: 'generic',
                        synthetic: false,
                    },
                    stacktrace: {
                        frames: [
                            {
                                colno: 220,
                                filename: 'https://app-static-prod.posthog.com/static/chunk-UFQKIDIH.js',
                                function: 'submitZendeskTicket',
                                in_app: true,
                                lineno: 25,
                            },
                        ],
                    },
                    type: 'Error',
                    value: 'There was an error creating the support ticket with zendesk2.',
                },
            ],
            $exception_personURL: 'https://app.posthog.com/person/f6kW3HXaha6dAvHZiOmgrcAXK09682P6nNPxvfjqM9c',
        }
        const result = getExceptionAttributes(eventProperties)
        expect(result).toEqual({
            browser: 'Chrome',
            browserVersion: '92.0.4515',
            value: 'There was an error creating the support ticket with zendesk2.',
            synthetic: false,
            type: 'Error',
            lib: 'posthog-js',
            libVersion: '1.0.0',
            level: undefined,
            os: 'Windows',
            osVersion: '10',
            url: undefined,
            runtime: 'web',
            sentryUrl: undefined,
            ingestionErrors: undefined,
            handled: true,
        })
    })

    // The tests above already cover a lone $level and no level key at all, which both resolve to
    // undefined. This only pins that $exception_level is the key we read.
    it('reads level from $exception_level', () => {
        const result = getExceptionAttributes({ $exception_level: 'fatal', $level: 'info' })
        expect(result.level).toEqual('fatal')
    })

    // Mobile SDKs report the platform in $os_name and leave $os unset, so reading $os alone left
    // iOS, Android, and React Native errors with no OS anywhere in the UI.
    // Non-string values must resolve to undefined: they reach PropertyIcon, whose lowercase lookup
    // would throw and take down the whole exception card.
    it.each([
        ['$os_name only', { $os_name: 'iOS' }, 'iOS'],
        ['$os only', { $os: 'Windows' }, 'Windows'],
        ['both keys', { $os_name: 'iPadOS', $os: 'Mac OS X' }, 'iPadOS'],
        ['neither key', {}, undefined],
        ['an empty $os_name', { $os_name: '', $os: 'Windows' }, 'Windows'],
        ['a non-string $os_name', { $os_name: 42, $os: 'Windows' }, 'Windows'],
        ['non-string values in both keys', { $os_name: 42, $os: {} }, undefined],
    ])('resolves os from %s', (_name, properties, expected) => {
        expect(getExceptionAttributes(properties).os).toEqual(expected)
    })

    it.each([
        ['a string $browser', { $browser: 'Chrome' }, 'Chrome'],
        ['a non-string $browser', { $browser: 42 }, undefined],
    ])('resolves browser from %s', (_name, properties, expected) => {
        expect(getExceptionAttributes(properties).browser).toEqual(expected)
    })

    // A non-string $session_id (e.g. a numeric timestamp from a misbehaving SDK) must not leak
    // through as a number — it used to crash the issue scene via a ts-pattern exhaustive match.
    it.each([
        ['valid string session id', { $session_id: 'the-session-id' }, 'the-session-id'],
        ['numeric session id', { $session_id: 1783346787081 }, undefined],
        ['empty string session id', { $session_id: '' }, undefined],
        ['missing session id', {}, undefined],
        ['null session id', { $session_id: null }, undefined],
    ])('getSessionId normalizes %s', (_name, properties, expected) => {
        expect(getSessionId(properties as ErrorEventProperties)).toEqual(expected)
    })

    it('normalizes the singular exception release property', () => {
        const release = getExceptionRelease({
            $exception_release: {
                id: '019aca26-0a47-776c-baa2-0afbec3ec7bb',
                version: '1.2.3',
                project: 'com.example.app',
                timestamp: '2026-08-04T10:00:00Z',
                metadata: {
                    git: {
                        commit_id: 'abcdef123456',
                    },
                },
            },
        } as ErrorEventProperties)

        expect(release).toEqual({
            id: '019aca26-0a47-776c-baa2-0afbec3ec7bb',
            version: '1.2.3',
            project: 'com.example.app',
            created_at: '2026-08-04T10:00:00Z',
            metadata: {
                git: {
                    commit_id: 'abcdef123456',
                },
            },
        })
    })

    it.each([
        ['missing release', {}],
        ['legacy plural release map', { $exception_releases: { release: { version: '1.2.3' } } }],
        ['non-object release', { $exception_release: '1.2.3' }],
        ['release without an id', { $exception_release: { version: '1.2.3', timestamp: '2026-08-04' } }],
        ['release without a version', { $exception_release: { id: 'release-id', timestamp: '2026-08-04' } }],
        ['release without a timestamp', { $exception_release: { id: 'release-id', version: '1.2.3' } }],
    ])('ignores an invalid %s', (_name, properties) => {
        expect(getExceptionRelease(properties as ErrorEventProperties)).toBeUndefined()
    })

    it.each([
        ['an apple frame', { raw_frame: { instruction_addr: '0x00000001010444e4' } }, '0x00000001010444e4'],
        ['a frame with no junk drawer', undefined, null],
        ['a junk drawer with no raw frame', {}, null],
        ['a raw frame with no address', { raw_frame: { colno: 12 } }, null],
        ['a null address', { raw_frame: { instruction_addr: null } }, null],
        ['a non-string address', { raw_frame: { instruction_addr: 4311089892 } }, null],
        ['a whitespace-only address', { raw_frame: { instruction_addr: '   ' } }, null],
        ['a padded address', { raw_frame: { instruction_addr: '  0x00000001010444e4 ' } }, '0x00000001010444e4'],
    ])('reads the instruction address from %s', (_name, junk_drawer, expected) => {
        expect(getInstructionAddress({ junk_drawer } as ErrorTrackingStackFrame)).toEqual(expected)
    })
})
