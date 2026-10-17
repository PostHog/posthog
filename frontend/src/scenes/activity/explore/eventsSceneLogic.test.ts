import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { tabUiStateLogic } from 'lib/logic/tabUiStateLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ActivityTab, PropertyFilterType, PropertyOperator } from '~/types'

import { getEventLookupQuery } from './defaults'
import { FlagCallsNote, eventsSceneLogic } from './eventsSceneLogic'

const LOOKUP_UUID = '018f0000-0000-7000-8000-000000000002'

describe('eventsSceneLogic', () => {
    let logic: ReturnType<typeof eventsSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/query': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        logic = eventsSceneLogic()
        logic.mount()
    })

    const drillDownQuery = (select?: string[]): DataTableNode => ({
        kind: NodeKind.DataTableNode,
        source: { kind: NodeKind.EventsQuery, ...(select ? { select } : {}), event: '$pageview', after: 'all' } as any,
        full: true,
    })

    test.each<[string, DataTableNode, DataTableNode]>([
        // The "View events" persons-modal action deep-links here with an events DataTableNode in the hash.
        [
            'a drill-down events query',
            drillDownQuery(['*', 'event', 'person', 'timestamp']),
            drillDownQuery(['*', 'event', 'person', 'timestamp']),
        ],
        [
            'an events query without select',
            drillDownQuery(),
            drillDownQuery(defaultDataTableColumns(NodeKind.EventsQuery)),
        ],
    ])('picks up %s from the #q= hash', async (_, query, expected) => {
        router.actions.push(combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: query }).url)

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.query).toEqual(expected)
    })

    test.each<[string, FlagEvaluationsModeEnumApi, Partial<EventsQuery>, FlagCallsNote | null]>([
        ['an unfiltered list', FlagEvaluationsModeEnumApi.Number2, {}, 'stored-separately'],
        [
            'a list filtered to another event',
            FlagEvaluationsModeEnumApi.Number2,
            { events: ['$pageview'] },
            'stored-separately',
        ],
        [
            'a list filtered to flag calls and another event',
            FlagEvaluationsModeEnumApi.Number2,
            { events: ['$feature_flag_called', '$pageview'] },
            'stored-separately',
        ],
        [
            'a list filtered to flag calls',
            FlagEvaluationsModeEnumApi.Number2,
            { events: ['$feature_flag_called'] },
            null,
        ],
        [
            'a list filtered to flag calls by the single event field',
            FlagEvaluationsModeEnumApi.Number2,
            { event: '$feature_flag_called' },
            null,
        ],
        [
            'a list filtered to flag calls and an action',
            FlagEvaluationsModeEnumApi.Number2,
            { event: '$feature_flag_called', actionId: 1 },
            'stored-separately',
        ],
        [
            'a list filtered to flag calls and action steps',
            FlagEvaluationsModeEnumApi.Number2,
            { event: '$feature_flag_called', actionSteps: [{ event: '$feature_flag_called' }] },
            'stored-separately',
        ],
        ['an unfiltered list on the read flag evaluations mode', FlagEvaluationsModeEnumApi.Number1, {}, null],
        [
            'flag calls over a range older than the retention window',
            FlagEvaluationsModeEnumApi.Number1,
            { event: '$feature_flag_called', after: '-180d' },
            'retention',
        ],
        [
            'flag calls over all time',
            FlagEvaluationsModeEnumApi.Number2,
            { events: ['$feature_flag_called'], after: 'all' },
            'retention',
        ],
        [
            'flag calls over a range inside the retention window',
            FlagEvaluationsModeEnumApi.Number1,
            { event: '$feature_flag_called', after: '-30d' },
            null,
        ],
        [
            'flag calls over all time on the events mode',
            FlagEvaluationsModeEnumApi.Number0,
            { event: '$feature_flag_called', after: 'all' },
            null,
        ],
    ])('decides which flag calls note shows for %s', (_name, mode, eventFilter, expected) => {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, flag_evaluations_mode: mode })
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: { kind: NodeKind.EventsQuery, select: ['*', 'event', 'timestamp'], ...eventFilter },
        }

        logic.actions.setQuery(query)

        expect(logic.values.flagCallsNote).toBe(expected)
    })

    test.each<
        [
            string,
            FlagEvaluationsModeEnumApi,
            Partial<EventsQuery>,
            'row' | 'no row' | 'error',
            'link' | 'link, then edit' | 'edit' | 'restore',
            string | undefined,
        ]
    >([
        [
            'a link to a flag call on mode 2',
            FlagEvaluationsModeEnumApi.Number2,
            {},
            'row',
            'link',
            '$feature_flag_called',
        ],
        [
            'a link on mode 2 that flag_evaluations does not hold',
            FlagEvaluationsModeEnumApi.Number2,
            {},
            'no row',
            'link',
            undefined,
        ],
        [
            'a link on mode 2 whose flag call query fails',
            FlagEvaluationsModeEnumApi.Number2,
            {},
            'error',
            'link',
            undefined,
        ],
        ['a link on mode 1', FlagEvaluationsModeEnumApi.Number1, {}, 'row', 'link', undefined],
        [
            'a link that names its event',
            FlagEvaluationsModeEnumApi.Number2,
            { event: '$pageview' },
            'row',
            'link',
            '$pageview',
        ],
        [
            'a link with another filter',
            FlagEvaluationsModeEnumApi.Number2,
            {
                properties: [
                    ...(getEventLookupQuery(LOOKUP_UUID).source as EventsQuery).properties!,
                    {
                        type: PropertyFilterType.Event,
                        key: '$browser',
                        operator: PropertyOperator.Exact,
                        value: 'Chrome',
                    },
                ],
            },
            'row',
            'link',
            undefined,
        ],
        [
            'a link whose query the user edits before the check answers',
            FlagEvaluationsModeEnumApi.Number2,
            {},
            'row',
            'link, then edit',
            undefined,
        ],
        ['an edit that clears the event of a lookup', FlagEvaluationsModeEnumApi.Number2, {}, 'row', 'edit', undefined],
        [
            'a restored tab whose lookup names no event',
            FlagEvaluationsModeEnumApi.Number2,
            {},
            'row',
            'restore',
            undefined,
        ],
    ])(
        'resolves the event name for %s',
        async (_name, mode, sourceOverrides, flagCallQuery, arrival, expectedEvent) => {
            const after = '2026-08-24T00:00:00.000Z'
            const before = '2026-08-24T00:00:30.000Z'
            useMocks({
                post: {
                    '/api/environments/:team_id/query/:kind': async ({ request }) => {
                        const { query } = (await request.json()) as Record<string, any>
                        const asksForTheFlagCall =
                            query.kind === NodeKind.EventsQuery &&
                            query.event === '$feature_flag_called' &&
                            JSON.stringify(query.properties).includes(LOOKUP_UUID) &&
                            query.after === after &&
                            query.before === before
                        if (asksForTheFlagCall && flagCallQuery === 'error') {
                            return [500, { detail: 'Query failed' }]
                        }
                        return [200, { results: asksForTheFlagCall && flagCallQuery === 'row' ? [[LOOKUP_UUID]] : [] }]
                    },
                },
            })
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, flag_evaluations_mode: mode })
            const lookup = getEventLookupQuery(LOOKUP_UUID)
            const query: DataTableNode = {
                ...lookup,
                source: { ...(lookup.source as EventsQuery), after, before, ...sourceOverrides },
            }

            const linkUrl = combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: query }).url
            switch (arrival) {
                case 'link':
                    router.actions.push(linkUrl)
                    break
                case 'link, then edit': {
                    router.actions.push(linkUrl)
                    const edited: DataTableNode = {
                        ...query,
                        source: { ...(query.source as EventsQuery), after: '-7d' },
                    }
                    logic.actions.setQuery(edited)
                    break
                }
                case 'edit':
                    logic.actions.setQuery(query)
                    break
                case 'restore':
                    tabUiStateLogic.actions.setSavedQueryForTab(undefined, 'events', query)
                    router.actions.push(urls.activity(ActivityTab.ExploreEvents))
                    break
            }
            await expectLogic(logic).toFinishAllListeners()

            expect(((logic.values.query as DataTableNode).source as EventsQuery).event).toBe(expectedEvent)
        }
    )

    it('keeps a cleared event when a later edit writes an undefined key', async () => {
        let flagCallQueries = 0
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const { query } = (await request.json()) as Record<string, any>
                    if (query.event !== '$feature_flag_called') {
                        return [200, { results: [] }]
                    }
                    flagCallQueries++
                    return [200, { results: [[LOOKUP_UUID]] }]
                },
            },
        })
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            flag_evaluations_mode: FlagEvaluationsModeEnumApi.Number2,
        })
        router.actions.push(
            combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: getEventLookupQuery(LOOKUP_UUID) }).url
        )
        await expectLogic(logic).toFinishAllListeners()
        const named = logic.values.query as DataTableNode
        const cleared: DataTableNode = { ...named, source: { ...(named.source as EventsQuery), event: '' } }
        const redated: DataTableNode = {
            ...cleared,
            source: { ...(cleared.source as EventsQuery), after: '-24h', before: undefined },
        }

        logic.actions.setQuery(cleared)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setQuery(redated)
        await expectLogic(logic).toFinishAllListeners()

        expect(((logic.values.query as DataTableNode).source as EventsQuery).event).toBe('')
        expect(flagCallQueries).toBe(1)
    })
})
