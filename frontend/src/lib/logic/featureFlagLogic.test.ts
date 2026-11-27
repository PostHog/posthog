import posthog, { type PostHog } from 'posthog-js'

import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'

import { initKeaTests } from '~/test/init'
import type { AppContext } from '~/types'

import {
    areClientFeatureFlagsHonored,
    featureFlagLogic,
    getPersistedFeatureFlags,
    peekFeatureFlag,
} from './featureFlagLogic'

describe('featureFlagLogic', () => {
    describe('areClientFeatureFlagsHonored', () => {
        afterEach(() => {
            delete window.JS_POSTHOG_SELF_CAPTURE
        })

        it.each([
            [null, false, false],
            [{ cloud: false, is_debug: false }, false, false],
            [{ cloud: true, is_debug: false }, false, true],
            [{ cloud: false, is_debug: true }, false, true],
            [{ cloud: true, is_debug: true }, false, true],
            [{ cloud: false, is_debug: false }, true, true],
            [null, true, true],
        ])('preflight %s with self-capture %s returns %s', (preflight, selfCapture, expected) => {
            window.JS_POSTHOG_SELF_CAPTURE = selfCapture
            expect(areClientFeatureFlagsHonored(preflight)).toBe(expected)
        })
    })

    describe('getPersistedFeatureFlags', () => {
        it('maps server-persisted flags to the enabled frontend baseline', () => {
            const appContext = {
                persisted_feature_flags: [FEATURE_FLAGS.WAREHOUSE_PERSON_PROPERTIES],
            } as AppContext

            expect(getPersistedFeatureFlags(appContext)).toEqual({
                [FEATURE_FLAGS.WAREHOUSE_PERSON_PROPERTIES]: true,
            })
        })
    })

    describe('scene menu bar', () => {
        it.each([
            ['on with today-rail-nav', { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true }, true],
            ['on by its own flag', { [FEATURE_FLAGS.SCENE_MENU_BAR]: true }, true],
            ['off without either flag', { [FEATURE_FLAGS.TODAY_RAIL_NAV]: false }, undefined],
        ])('is %s', (_name, variants, expected) => {
            initKeaTests()
            const logic = featureFlagLogic()
            logic.mount()

            logic.actions.setFeatureFlags(Object.keys(variants), variants)

            expect(logic.values.featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]).toBe(expected)
        })
    })

    describe('flags from posthog-js', () => {
        const FLAG = 'flag-created-after-the-last-visit'
        const OTHER_FLAG = 'some-other-flag'

        type FlagsAnswer = Record<string, boolean> | 'blocked' | 'in flight'
        type PageVisit = {
            pageFlags: Record<string, boolean>
            flagsAnswers: FlagsAnswer[]
            afterLoad?: (sdk: PostHog) => void
            mountAfterLoad?: boolean
            flagErrors?: boolean
        }

        function openPage({ pageFlags, flagsAnswers, flagErrors }: PageVisit): PostHog {
            window.POSTHOG_USER_IDENTITY_WITH_FLAGS = {
                distinctID: 'person-1',
                isIdentifiedID: true,
                featureFlags: pageFlags,
            }
            delete window.POSTHOG_GLOBAL_ERRORS
            global.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
                if (!String(url).startsWith(`${SDK_HOST}/flags/`)) {
                    return suiteFetch(url, init)
                }
                const answer = flagsAnswers.shift() ?? 'blocked'
                if (answer === 'blocked') {
                    throw new TypeError('Failed to fetch')
                }
                if (answer === 'in flight') {
                    return new Promise<Response>(() => {})
                }
                const flags = Object.entries(answer).map(([key, enabled]) => [key, { key, enabled, variant: null }])
                return new Response(
                    JSON.stringify({ flags: Object.fromEntries(flags), errorsWhileComputingFlags: flagErrors }),
                    { status: 200 }
                )
            }) as typeof fetch
            let sdk: PostHog | undefined
            jest.isolateModules(() => {
                sdk = new (jest.requireActual<typeof import('posthog-js')>('posthog-js').PostHog)()
            })
            if (!sdk) {
                throw new Error('posthog-js did not load')
            }
            sdk.init('phc_test', {
                api_host: SDK_HOST,
                persistence: 'localStorage',
                bootstrap: window.POSTHOG_USER_IDENTITY_WITH_FLAGS,
                advanced_disable_feature_flags_on_first_load: true,
                autocapture: false,
                capture_pageview: false,
                disable_session_recording: true,
                disable_surveys: true,
            })
            sdk.onFeatureFlags((_flags, _variants, context) => {
                if (context?.errorsLoading) {
                    window.POSTHOG_GLOBAL_ERRORS = { onFeatureFlagsLoadError: true }
                }
            })
            return sdk
        }

        async function visit(page: PageVisit): Promise<void> {
            const sdk = openPage(page)
            sdk.reloadFeatureFlags()
            await jest.advanceTimersByTimeAsync(100)
            page.afterLoad?.(sdk)
            await jest.advanceTimersByTimeAsync(100)
        }

        const SDK_HOST = 'https://us.i.posthog.com'
        let suiteFetch: typeof fetch

        beforeEach(() => {
            suiteFetch = global.fetch
            jest.useFakeTimers()
            window.localStorage.clear()
        })

        afterEach(() => {
            global.fetch = suiteFetch
            jest.useRealTimers()
            window.localStorage.clear()
            delete window.POSTHOG_USER_IDENTITY_WITH_FLAGS
            delete window.POSTHOG_GLOBAL_ERRORS
            jest.mocked(posthog.onFeatureFlags).mockImplementation(() => () => {})
            jest.mocked(posthog.get_property).mockReset()
        })

        it.each<[string, PageVisit[], PageVisit, boolean | undefined]>([
            [
                'a blocked request keeps a flag the page decided on',
                [{ pageFlags: { [OTHER_FLAG]: true }, flagsAnswers: ['blocked'] }],
                { pageFlags: { [OTHER_FLAG]: true, [FLAG]: true }, flagsAnswers: ['blocked'] },
                true,
            ],
            [
                'a blocked request turns off a stored flag the page decided off',
                [{ pageFlags: { [FLAG]: true }, flagsAnswers: [{ [FLAG]: true }] }],
                { pageFlags: { [FLAG]: false }, flagsAnswers: ['blocked'] },
                undefined,
            ],
            [
                'a blocked request keeps a stored flag the page left undecided',
                [{ pageFlags: { [FLAG]: true }, flagsAnswers: [{ [FLAG]: true }] }],
                { pageFlags: { [OTHER_FLAG]: true }, flagsAnswers: ['blocked'] },
                true,
            ],
            [
                'a blocked request keeps an early access opt-out',
                [
                    {
                        pageFlags: { [OTHER_FLAG]: true },
                        flagsAnswers: ['blocked'],
                        afterLoad: (sdk) => sdk.updateEarlyAccessFeatureEnrollment(FLAG, false),
                    },
                ],
                { pageFlags: { [OTHER_FLAG]: true, [FLAG]: true }, flagsAnswers: ['blocked'] },
                undefined,
            ],
            [
                'a blocked request keeps a local override',
                [
                    {
                        pageFlags: { [OTHER_FLAG]: true },
                        flagsAnswers: ['blocked'],
                        afterLoad: (sdk) => sdk.featureFlags.overrideFeatureFlags({ flags: { [FLAG]: false } }),
                    },
                ],
                { pageFlags: { [OTHER_FLAG]: true, [FLAG]: true }, flagsAnswers: ['blocked'] },
                undefined,
            ],
            [
                'a blocked request keeps the page decision through a later early access change',
                [{ pageFlags: { [OTHER_FLAG]: true }, flagsAnswers: ['blocked'] }],
                {
                    pageFlags: { [OTHER_FLAG]: true, [FLAG]: true },
                    flagsAnswers: ['blocked', 'in flight'],
                    afterLoad: (sdk) => sdk.updateEarlyAccessFeatureEnrollment(OTHER_FLAG, false),
                },
                true,
            ],
            [
                'a successful load wins over the page decision',
                [{ pageFlags: { [OTHER_FLAG]: true }, flagsAnswers: [{ [OTHER_FLAG]: true }] }],
                { pageFlags: { [OTHER_FLAG]: true, [FLAG]: true }, flagsAnswers: [{ [OTHER_FLAG]: true }] },
                undefined,
            ],
            [
                'a blocked request that fails before the app mounts keeps a flag the page decided on',
                [{ pageFlags: { [OTHER_FLAG]: true }, flagsAnswers: ['blocked'] }],
                {
                    pageFlags: { [OTHER_FLAG]: true, [FLAG]: true },
                    flagsAnswers: ['blocked'],
                    mountAfterLoad: true,
                },
                true,
            ],
            [
                'a successful load that arrives before the app mounts wins over the page decision',
                [{ pageFlags: { [OTHER_FLAG]: true }, flagsAnswers: [{ [OTHER_FLAG]: true }] }],
                {
                    pageFlags: { [OTHER_FLAG]: true, [FLAG]: true },
                    flagsAnswers: [{ [OTHER_FLAG]: true }],
                    mountAfterLoad: true,
                },
                undefined,
            ],
            [
                'an answer with flag errors that arrives before the app mounts wins over the page decision',
                [{ pageFlags: { [OTHER_FLAG]: true }, flagsAnswers: [{ [OTHER_FLAG]: true }] }],
                {
                    pageFlags: { [OTHER_FLAG]: true, [FLAG]: true },
                    flagsAnswers: [{ [OTHER_FLAG]: true, [FLAG]: false }],
                    flagErrors: true,
                    mountAfterLoad: true,
                },
                undefined,
            ],
            [
                'a successful load still wins after a later refresh fails',
                [{ pageFlags: { [OTHER_FLAG]: true }, flagsAnswers: [{ [OTHER_FLAG]: true }] }],
                {
                    pageFlags: { [OTHER_FLAG]: true, [FLAG]: true },
                    flagsAnswers: [{ [OTHER_FLAG]: true }, 'blocked'],
                    afterLoad: (sdk) => sdk.reloadFeatureFlags(),
                },
                undefined,
            ],
        ])('%s', async (_name, earlierVisits, today, expected) => {
            for (const earlierVisit of earlierVisits) {
                await visit(earlierVisit)
            }
            const sdk = openPage(today)
            jest.mocked(posthog.onFeatureFlags).mockImplementation((callback) => sdk.onFeatureFlags(callback))
            jest.mocked(posthog.get_property).mockImplementation((key) => sdk.get_property(key))
            if (today.mountAfterLoad) {
                sdk.reloadFeatureFlags()
                await jest.advanceTimersByTimeAsync(100)
            }
            initKeaTests()
            const logic = featureFlagLogic()
            logic.mount()
            if (!today.mountAfterLoad) {
                sdk.reloadFeatureFlags()
                await jest.advanceTimersByTimeAsync(100)
            }
            today.afterLoad?.(sdk)
            await jest.advanceTimersByTimeAsync(100)

            expect(peekFeatureFlag(logic.values.featureFlags, FLAG as FeatureFlagKey)).toBe(expected)
        })
    })

    describe('receivedFeatureFlags', () => {
        afterEach(() => {
            delete (posthog as any).config
        })

        // The mocked onFeatureFlags never calls back, as posthog-js does not when flags are off.
        it.each([
            ['flags disabled', { advanced_disable_flags: true }, true],
            ['flags enabled', { advanced_disable_flags: false }, false],
        ])('with %s is %s before any flags arrive', (_name, config, expected) => {
            ;(posthog as any).config = config
            initKeaTests()

            const logic = featureFlagLogic()
            logic.mount()

            expect(logic.values.receivedFeatureFlags).toBe(expected)
        })
    })
})
