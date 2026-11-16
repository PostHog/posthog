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

    const relatedRow = (uuid: string, event: string): any[] => [
        uuid,
        event,
        '2024-01-01T00:02:00Z',
        '',
        null,
        null,
        null,
        'distinct-id',
    ]

    const mockQueries = ({
        eventsFails = false,
        flagEvaluationsFails = false,
        eventsRows,
        flagEvaluationsRows,
    }: {
        eventsFails?: boolean
        flagEvaluationsFails?: boolean
        eventsRows: (query: string) => any[][]
        flagEvaluationsRows: (query: string) => any[][]
    }): void => {
        jest.spyOn(api, 'queryHogQL').mockImplementation(async (query: string) => {
            const readsFlagEvaluations = query.includes('posthog.flag_evaluations')
            if (readsFlagEvaluations ? flagEvaluationsFails : eventsFails) {
                throw new Error('timeout')
            }
            return { results: readsFlagEvaluations ? flagEvaluationsRows(query) : eventsRows(query) } as any
        })
    }

    // A load can trigger a preload that repeats the failing read, so this compares which features reported, not how often.
    const reportedFailures = (): string[] =>
        Array.from(
            new Set(
                jest.mocked(posthog.captureException).mock.calls.map(([, properties]) => (properties as any)?.feature)
            )
        )

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
    // `server-flag-call` has no session id, so only the person's related flag calls include it.
    it.each([
        {
            flagCallsOnlyInFlagEvaluations: true,
            flagEvaluationsFails: false,
            expectedIds: ['pageview', 'both', 'flag-evaluation-only', 'server-flag-call'],
            expectedFailures: [],
        },
        {
            flagCallsOnlyInFlagEvaluations: true,
            flagEvaluationsFails: true,
            expectedIds: ['pageview', 'both'],
            expectedFailures: ['session-recording-flag-evaluations'],
        },
        {
            flagCallsOnlyInFlagEvaluations: false,
            flagEvaluationsFails: false,
            expectedIds: ['pageview', 'both'],
            expectedFailures: [],
        },
    ])(
        'lists the session events when flagCallsOnlyInFlagEvaluations is $flagCallsOnlyInFlagEvaluations and the flag_evaluations read fails: $flagEvaluationsFails',
        async ({ flagCallsOnlyInFlagEvaluations, flagEvaluationsFails, expectedIds, expectedFailures }) => {
            setFlagCallsOnlyInFlagEvaluations(flagCallsOnlyInFlagEvaluations)
            mockQueries({
                flagEvaluationsFails,
                flagEvaluationsRows: (query) =>
                    query.includes('empty(session_id)')
                        ? [relatedRow('server-flag-call', '$feature_flag_called')]
                        : [row('both', '$feature_flag_called'), row('flag-evaluation-only', '$feature_flag_called')],
                eventsRows: (query) =>
                    query.includes('$session_id =')
                        ? [row('pageview', '$pageview'), row('both', '$feature_flag_called')]
                        : [],
            })

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMetaSuccess(recordingMeta)
            }).toDispatchActions(['loadEventsSuccess'])

            expect(logic.values.sessionEventsData?.map((e) => e.id)).toEqual(expectedIds)
            expect(reportedFailures()).toEqual(expectedFailures)
        }
    )

    it.each([
        {
            flagCallsOnlyInFlagEvaluations: true,
            eventsFails: false,
            flagEvaluationsFails: false,
            expectedProperties: [
                { $current_url: 'https://example.com/' },
                { $feature_flag: 'from-events' },
                { $feature_flag: 'from-flag-evaluations' },
            ],
            expectedFullyLoaded: [true, true, true],
            expectedFailures: [],
        },
        {
            flagCallsOnlyInFlagEvaluations: true,
            eventsFails: false,
            flagEvaluationsFails: true,
            expectedProperties: [{ $current_url: 'https://example.com/' }, { $feature_flag: 'from-events' }, {}],
            expectedFullyLoaded: [true, true, true],
            expectedFailures: ['session-recording-flag-evaluations'],
        },
        {
            flagCallsOnlyInFlagEvaluations: true,
            eventsFails: true,
            flagEvaluationsFails: false,
            expectedProperties: [
                {},
                { $feature_flag: 'from-flag-evaluations' },
                { $feature_flag: 'from-flag-evaluations' },
            ],
            expectedFullyLoaded: [true, true, true],
            expectedFailures: ['session-recording-load-full-event-data'],
        },
        {
            flagCallsOnlyInFlagEvaluations: false,
            eventsFails: false,
            flagEvaluationsFails: false,
            expectedProperties: [{ $current_url: 'https://example.com/' }, { $feature_flag: 'from-events' }, {}],
            expectedFullyLoaded: [true, true, false],
            expectedFailures: [],
        },
    ])(
        'loads full properties when flagCallsOnlyInFlagEvaluations is $flagCallsOnlyInFlagEvaluations, the events read fails: $eventsFails, and the flag_evaluations read fails: $flagEvaluationsFails',
        async ({
            flagCallsOnlyInFlagEvaluations,
            eventsFails,
            flagEvaluationsFails,
            expectedProperties,
            expectedFullyLoaded,
            expectedFailures,
        }) => {
            setFlagCallsOnlyInFlagEvaluations(flagCallsOnlyInFlagEvaluations)
            const pageview = makeEvent('pageview')
            const flagCallInBoth = makeEvent('both', '$feature_flag_called')
            const flagCall = makeEvent('flag-evaluation-only', '$feature_flag_called')
            logic.actions.loadEventsSuccess([pageview, flagCallInBoth, flagCall])
            mockQueries({
                eventsFails,
                flagEvaluationsFails,
                flagEvaluationsRows: () => [
                    [JSON.stringify({ $feature_flag: 'from-flag-evaluations' }), 'both'],
                    [JSON.stringify({ $feature_flag: 'from-flag-evaluations' }), 'flag-evaluation-only'],
                ],
                eventsRows: () => [
                    [JSON.stringify({ $current_url: 'https://example.com/' }), 'pageview'],
                    [JSON.stringify({ $feature_flag: 'from-events' }), 'both'],
                ],
            })

            await expectLogic(logic, () => {
                logic.actions.loadFullEventData([pageview, flagCallInBoth, flagCall])
            }).toDispatchActions(['loadFullEventDataSuccess'])

            expect(logic.values.sessionEventsData?.map((e) => e.properties)).toEqual(expectedProperties)
            expect(logic.values.sessionEventsData?.map((e) => e.fullyLoaded)).toEqual(expectedFullyLoaded)
            expect(reportedFailures()).toEqual(expectedFailures)
        }
    )

    // New York repeats 01:00-02:00 on 2026-11-01. 05:58Z is 01:58 EDT and 06:02Z is 01:02 EST.
    it('finds the properties of flag calls in the hour a daylight saving change repeats', async () => {
        const appContext = window.POSTHOG_APP_CONTEXT
        window.POSTHOG_APP_CONTEXT = {
            ...appContext,
            current_team: { ...appContext?.current_team, timezone: 'America/New_York' },
        } as any
        try {
            setFlagCallsOnlyInFlagEvaluations(true)
            const before = { ...makeEvent('before', '$feature_flag_called'), timestamp: '2026-11-01T05:58:00Z' }
            const after = { ...makeEvent('after', '$feature_flag_called'), timestamp: '2026-11-01T06:02:00Z' }
            logic.actions.loadEventsSuccess([before, after])
            const bound = (query: string, operator: string): string =>
                query.match(new RegExp(`timestamp ${operator} [^']*'([^']+)'`))?.[1] ?? ''
            mockQueries({
                flagEvaluationsRows: (query) =>
                    bound(query, '>') < bound(query, '<')
                        ? [
                              [JSON.stringify({ $feature_flag: 'before' }), 'before'],
                              [JSON.stringify({ $feature_flag: 'after' }), 'after'],
                          ]
                        : [],
                eventsRows: () => [],
            })

            await expectLogic(logic, () => {
                logic.actions.loadFullEventData([before, after])
            }).toDispatchActions(['loadFullEventDataSuccess'])

            expect(logic.values.sessionEventsData?.map((e) => e.properties)).toEqual([
                { $feature_flag: 'before' },
                { $feature_flag: 'after' },
            ])
        } finally {
            window.POSTHOG_APP_CONTEXT = appContext
        }
    })
})
