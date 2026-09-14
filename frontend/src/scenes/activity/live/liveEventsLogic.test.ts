import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, LiveEvent, PropertyFilterType, PropertyOperator } from '~/types'

import { liveEventsLogic } from './liveEventsLogic'
import { liveEventsTableSceneLogic } from './liveEventsTableSceneLogic'

function makeLiveEvent(currentUrl?: string): LiveEvent {
    return {
        uuid: 'abc',
        event: '$pageview',
        properties: currentUrl !== undefined ? { $current_url: currentUrl } : {},
        timestamp: '2026-01-01T00:00:00Z',
        team_id: 1,
        distinct_id: 'user-1',
        created_at: '2026-01-01T00:00:00Z',
    }
}

function eventFilter(key: string, operator: PropertyOperator, value?: AnyPropertyFilter['value']): AnyPropertyFilter {
    return { type: PropertyFilterType.Event, key, operator, value } as AnyPropertyFilter
}

describe('liveEventsLogic', () => {
    let logic: ReturnType<typeof liveEventsLogic.build>
    let flagsLogic: ReturnType<typeof featureFlagLogic.build>
    let streamSpy: jest.SpyInstance
    let toastSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        streamSpy = jest.spyOn(api, 'stream').mockResolvedValue(undefined as any)
        toastSpy = jest.spyOn(lemonToast, 'error').mockReturnValue(undefined as any)
        flagsLogic = featureFlagLogic()
        flagsLogic.mount()
        logic = liveEventsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        flagsLogic?.unmount()
        streamSpy.mockRestore()
        toastSpy.mockRestore()
    })

    function setRichFiltersFlag(enabled: boolean): void {
        flagsLogic.actions.setFeatureFlags(
            enabled ? [FEATURE_FLAGS.LIVE_EVENTS_RICH_FILTERS] : [],
            enabled ? { [FEATURE_FLAGS.LIVE_EVENTS_RICH_FILTERS]: true } : {}
        )
    }

    function lastStreamUrl(): URL {
        const calls = streamSpy.mock.calls
        if (calls.length === 0) {
            throw new Error('api.stream was not called')
        }
        return new URL(calls[calls.length - 1][0] as string)
    }

    describe('addEvents host extraction', () => {
        it('records the host for a valid $current_url', async () => {
            await expectLogic(logic, () => {
                logic.actions.addEvents([makeLiveEvent('https://app.posthog.com/insights')])
            }).toMatchValues({
                eventHosts: ['https://app.posthog.com'],
            })
        })

        it.each([
            ['malformed URL', 'not a url'],
            ['empty host', 'https://'],
            ['missing $current_url', undefined],
        ])('does not throw and records no host for %s', async (_label, currentUrl) => {
            await expectLogic(logic, () => {
                logic.actions.addEvents([makeLiveEvent(currentUrl)])
            }).toMatchValues({
                eventHosts: [],
            })
        })
    })

    describe('stream errors', () => {
        function lastStreamOptions(): { onError: (error: any) => void; onOpen?: () => void } {
            const calls = streamSpy.mock.calls
            if (calls.length === 0) {
                throw new Error('api.stream was not called')
            }
            return calls[calls.length - 1][1]
        }

        function streamErrorCaptures(): unknown[] {
            return jest.mocked(posthog.capture).mock.calls.filter(([name]) => name === 'livestream_sse_error')
        }

        it.each([
            [401, 'This project cannot read the live event stream.'],
            [504, 'The live event stream failed with error 504.'],
        ])('surfaces an http %s as a non-retrying error', async (status, expectedStart) => {
            await expectLogic(logic, () => {
                lastStreamOptions().onError(new ApiError(undefined, status))
            }).toMatchValues({ streamError: { message: expect.stringContaining(expectedStart), retrying: false } })
        })

        it('marks a transport error as retrying', async () => {
            await expectLogic(logic, () => {
                lastStreamOptions().onError(new TypeError('Failed to fetch'))
            }).toMatchValues({ streamError: { message: expect.any(String), retrying: true } })
        })

        it('clears the error once the stream opens again', async () => {
            lastStreamOptions().onError(new ApiError(undefined, 504))
            await expectLogic(logic, () => {
                lastStreamOptions().onOpen?.()
            }).toMatchValues({ streamError: null })
        })

        it.each([
            ['on its own, so onboarding stays quiet', false],
            ['once the live events scene is mounted', true],
        ])('toasts %s', (_label, sceneMounted) => {
            const sceneLogic = sceneMounted ? liveEventsTableSceneLogic() : null
            sceneLogic?.mount()

            lastStreamOptions().onError(new ApiError(undefined, 504))

            expect(toastSpy).toHaveBeenCalledTimes(sceneMounted ? 1 : 0)
            sceneLogic?.unmount()
        })

        it('reports a repeating reconnect failure once, and reports a different one again', () => {
            const options = lastStreamOptions()

            options.onError(new TypeError('Failed to fetch'))
            options.onError(new TypeError('Failed to fetch'))
            options.onError(new TypeError('Failed to fetch'))
            expect(streamErrorCaptures()).toHaveLength(1)

            options.onError(new ApiError(undefined, 502))
            expect(streamErrorCaptures()).toHaveLength(2)
        })

        it('reports a reconnect failure again once the stream has recovered', () => {
            const options = lastStreamOptions()

            options.onError(new TypeError('Failed to fetch'))
            options.onOpen?.()
            options.onError(new TypeError('Failed to fetch'))

            expect(streamErrorCaptures()).toHaveLength(2)
        })

        it('does not connect without a live events token, and says so', async () => {
            streamSpy.mockClear()
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, live_events_token: '' })

            await expectLogic(logic, () => {
                logic.actions.updateEventsConnection()
            }).toMatchValues({ streamError: { message: expect.any(String), retrying: false } })
            expect(streamSpy).not.toHaveBeenCalled()
        })
    })

    describe('connection lifecycle', () => {
        it.each([
            ['leaves a stream that was never paused alone', false, 1],
            ['reconnects a stream that was paused', true, 2],
        ])('resuming %s', (_label, pauseFirst, expectedConnections) => {
            expect(streamSpy).toHaveBeenCalledTimes(1)

            if (pauseFirst) {
                logic.actions.pauseStream()
            }
            logic.actions.resumeStream()

            expect(streamSpy).toHaveBeenCalledTimes(expectedConnections)
        })
    })

    describe('stream URL property filters', () => {
        it.each([
            {
                label: 'emits legacy property= params and drops non-exact operators',
                properties: [
                    eventFilter('$current_url', PropertyOperator.Exact, 'https://app.posthog.com'),
                    eventFilter('$browser', PropertyOperator.IContains, 'chrome'),
                ],
                expectedProperty: ['$current_url=https://app.posthog.com'],
            },
            {
                label: 'expands a multi-value exact filter into repeated legacy params',
                properties: [eventFilter('$browser', PropertyOperator.Exact, ['Chrome', 'Firefox'])],
                expectedProperty: ['$browser=Chrome', '$browser=Firefox'],
            },
        ])('with the flag off, $label', ({ properties, expectedProperty }) => {
            setRichFiltersFlag(false)
            logic.actions.setFilters({ properties })

            const url = lastStreamUrl()
            expect(url.searchParams.getAll('property')).toEqual(expectedProperty)
            expect(url.searchParams.has('properties')).toBe(false)
        })

        it.each([
            {
                label: 'emits a single JSON properties param',
                properties: [
                    eventFilter('$current_url', PropertyOperator.IContains, 'checkout'),
                    eventFilter('$browser', PropertyOperator.Exact, ['Chrome', 'Firefox']),
                    eventFilter('amount', PropertyOperator.GreaterThan, 100),
                    eventFilter('$referrer', PropertyOperator.IsSet),
                ],
                expectedProperties: [
                    { key: '$current_url', operator: 'icontains', value: 'checkout' },
                    { key: '$browser', operator: 'exact', value: ['Chrome', 'Firefox'] },
                    { key: 'amount', operator: 'gt', value: 100 },
                    { key: '$referrer', operator: 'is_set' },
                ],
            },
            {
                label: 'skips null values, empty arrays, and unsupported operators',
                properties: [
                    eventFilter('$current_url', PropertyOperator.Exact, null),
                    eventFilter('$browser', PropertyOperator.Exact, []),
                    eventFilter('$pathname', PropertyOperator.Between, '5'),
                    eventFilter('$os', PropertyOperator.IContains, 'mac'),
                ],
                expectedProperties: [{ key: '$os', operator: 'icontains', value: 'mac' }],
            },
            {
                label: 'omits the properties param entirely when nothing is eligible',
                properties: [eventFilter('$current_url', PropertyOperator.Exact, null)],
                expectedProperties: null,
            },
        ])('with the flag on, $label', ({ properties, expectedProperties }) => {
            setRichFiltersFlag(true)
            logic.actions.setFilters({ properties })

            const url = lastStreamUrl()
            expect(url.searchParams.has('property')).toBe(false)
            if (expectedProperties === null) {
                expect(url.searchParams.has('properties')).toBe(false)
            } else {
                expect(JSON.parse(url.searchParams.get('properties')!)).toEqual(expectedProperties)
            }
        })
    })
})
