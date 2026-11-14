import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { RecordingEventType, SessionRecordingType } from '~/types'

import { sessionEventsDataLogic } from './sessionEventsDataLogic'

describe('sessionEventsDataLogic', () => {
    let logic: ReturnType<typeof sessionEventsDataLogic.build>

    const makeEvent = (id: string, event = '$pageview'): RecordingEventType => ({
        id,
        event,
        timestamp: '2024-01-01T00:00:00Z',
        elements: [],
        properties: {},
        playerTime: 0,
        fullyLoaded: false,
        distinct_id: 'distinct-id',
    })

    beforeEach(() => {
        initKeaTests()
        logic = sessionEventsDataLogic({ sessionRecordingId: 'test-session' })
        logic.mount()
        jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
    })

    const recordingMeta = {
        id: 'test-session',
        start_time: '2024-01-01T00:00:00Z',
        end_time: '2024-01-01T00:10:00Z',
        person: { uuid: 'person-uuid' },
    } as unknown as SessionRecordingType

    const row = (uuid: string, event: string): any[] => [
        uuid,
        event,
        '2024-01-01T00:01:00Z',
        '',
        'window-id',
        'https://example.com/',
        null,
        null,
        null,
        null,
        'distinct-id',
    ]

    const setFlagCallsOnlyInFlagEvaluations = (value: boolean): void => {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, flag_calls_only_in_flag_evaluations: value })
    }

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    // Regression test: a second loadFullEventData call supersedes the first via kea's
    // breakpoint mechanism, which throws 'kea-listeners breakpoint broke'. Without an
    // isBreakpoint guard, the superseded call's catch block ran anyway and marked its
    // events fullyLoaded, so their properties were never fetched again.
    it('does not mark a superseded loadFullEventData call as fully loaded, nor report it as an error', async () => {
        const eventOne = makeEvent('event-1')
        const eventTwo = makeEvent('event-2')
        logic.actions.loadEventsSuccess([eventOne, eventTwo])

        let resolveFirstQuery: (value: any) => void = () => {}
        const firstQuery = new Promise((resolve) => {
            resolveFirstQuery = resolve
        })
        jest.spyOn(api, 'queryHogQL')
            .mockReturnValueOnce(firstQuery as any)
            .mockResolvedValueOnce({ results: [[JSON.stringify({ some: 'value' }), 'event-2']] } as any)

        logic.actions.loadFullEventData(eventOne)
        logic.actions.loadFullEventData(eventTwo)

        resolveFirstQuery({ results: [[JSON.stringify({ some: 'value' }), 'event-1']] })

        await expectLogic(logic).toDispatchActions(['loadFullEventDataSuccess'])

        expect(posthog.captureException).not.toHaveBeenCalled()
        expect(logic.values.sessionEventsData?.find((e) => e.id === 'event-1')?.fullyLoaded).toBe(false)
        expect(logic.values.sessionEventsData?.find((e) => e.id === 'event-2')?.fullyLoaded).toBe(true)
    })

    // flag_evaluations holds every flag call. The events table holds only the copy written before the move, `both`.
    it.each([
        {
            flagCallsOnlyInFlagEvaluations: true,
            flagEvaluationsFails: false,
            expectedIds: ['pageview', 'both', 'flag-evaluation-only'],
        },
        { flagCallsOnlyInFlagEvaluations: true, flagEvaluationsFails: true, expectedIds: ['pageview', 'both'] },
        { flagCallsOnlyInFlagEvaluations: false, flagEvaluationsFails: false, expectedIds: ['pageview', 'both'] },
    ])(
        'lists the session events when flagCallsOnlyInFlagEvaluations is $flagCallsOnlyInFlagEvaluations and the flag_evaluations read fails: $flagEvaluationsFails',
        async ({ flagCallsOnlyInFlagEvaluations, flagEvaluationsFails, expectedIds }) => {
            setFlagCallsOnlyInFlagEvaluations(flagCallsOnlyInFlagEvaluations)
            jest.spyOn(api, 'queryHogQL').mockImplementation(async (query: string) => {
                if (query.includes('posthog.flag_evaluations')) {
                    if (flagEvaluationsFails) {
                        throw new Error('timeout')
                    }
                    return {
                        results: [
                            row('both', '$feature_flag_called'),
                            row('flag-evaluation-only', '$feature_flag_called'),
                        ],
                    } as any
                }
                if (query.includes('$session_id =')) {
                    return { results: [row('pageview', '$pageview'), row('both', '$feature_flag_called')] } as any
                }
                return { results: [] } as any
            })

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMetaSuccess(recordingMeta)
            }).toDispatchActions(['loadEventsSuccess'])

            expect(logic.values.sessionEventsData?.map((e) => e.id)).toEqual(expectedIds)
        }
    )

    it.each([
        {
            flagEvaluationsFails: false,
            expectedProperties: [
                { $current_url: 'https://example.com/' },
                { $feature_flag: 'from-events' },
                { $feature_flag: 'from-flag-evaluations' },
            ],
        },
        {
            flagEvaluationsFails: true,
            expectedProperties: [{ $current_url: 'https://example.com/' }, { $feature_flag: 'from-events' }, {}],
        },
    ])(
        'loads full properties from both tables, preferring the events copy, when the flag_evaluations read fails: $flagEvaluationsFails',
        async ({ flagEvaluationsFails, expectedProperties }) => {
            setFlagCallsOnlyInFlagEvaluations(true)
            const pageview = makeEvent('pageview')
            const flagCallInBoth = makeEvent('both', '$feature_flag_called')
            const flagCall = makeEvent('flag-evaluation-only', '$feature_flag_called')
            logic.actions.loadEventsSuccess([pageview, flagCallInBoth, flagCall])
            jest.spyOn(api, 'queryHogQL').mockImplementation(async (query: string) => {
                if (query.includes('posthog.flag_evaluations')) {
                    if (flagEvaluationsFails) {
                        throw new Error('timeout')
                    }
                    return {
                        results: [
                            [JSON.stringify({ $feature_flag: 'from-flag-evaluations' }), 'both'],
                            [JSON.stringify({ $feature_flag: 'from-flag-evaluations' }), 'flag-evaluation-only'],
                        ],
                    } as any
                }
                return {
                    results: [
                        [JSON.stringify({ $current_url: 'https://example.com/' }), 'pageview'],
                        [JSON.stringify({ $feature_flag: 'from-events' }), 'both'],
                    ],
                } as any
            })

            await expectLogic(logic, () => {
                logic.actions.loadFullEventData([pageview, flagCallInBoth, flagCall])
            }).toDispatchActions(['loadFullEventDataSuccess'])

            expect(logic.values.sessionEventsData?.map((e) => e.properties)).toEqual(expectedProperties)
        }
    )
})
