import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, LiveEvent, PropertyFilterType, PropertyOperator } from '~/types'

import { liveEventsLogic } from './liveEventsLogic'

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

    beforeEach(() => {
        initKeaTests()
        streamSpy = jest.spyOn(api, 'stream').mockResolvedValue(undefined as any)
        flagsLogic = featureFlagLogic()
        flagsLogic.mount()
        logic = liveEventsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        flagsLogic?.unmount()
        streamSpy.mockRestore()
    })

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
        ])('$label', ({ properties, expectedProperty }) => {
            logic.actions.setFilters({ properties })

            const url = lastStreamUrl()
            expect(url.searchParams.getAll('property')).toEqual(expectedProperty)
            expect(url.searchParams.has('properties')).toBe(false)
        })
    })
})
