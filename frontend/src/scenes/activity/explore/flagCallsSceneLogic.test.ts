import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { DataTableNode, EventsQuery, Node, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ActivityTab } from '~/types'

import { flagCallsSceneLogic, getDefaultFlagCallsSceneQuery } from './flagCallsSceneLogic'

function flagCallsQuery(source: Partial<EventsQuery>): DataTableNode {
    const query = getDefaultFlagCallsSceneQuery()
    return { ...query, source: { ...query.source, ...source } }
}

describe('flagCallsSceneLogic', () => {
    let logic: ReturnType<typeof flagCallsSceneLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        logic = flagCallsSceneLogic()
        logic.mount()
    })

    it('loads a query from the URL', async () => {
        const query = flagCallsQuery({ after: '-7d' })

        router.actions.push(combineUrl(urls.activity(ActivityTab.ExploreFlagCalls), {}, { q: query }).url)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.query).toEqual(query)
    })

    // Any filter other than the flag call event alone makes the runner read the events table, which holds no new flag calls.
    test.each<[string, Partial<EventsQuery>]>([
        ['another event', { event: '$pageview' }],
        ['a list of events', { event: undefined, events: ['$pageview', '$feature_flag_called'] }],
        ['an action', { actionId: 1 }],
        ['action steps', { actionSteps: [{ event: '$pageview' }] }],
        [
            'a nested source',
            { source: { kind: NodeKind.InsightActorsQuery, source: { kind: NodeKind.TrendsQuery, series: [] } } },
        ],
    ])('keeps a URL query with %s on flag calls', async (_name, source) => {
        router.actions.push(
            combineUrl(urls.activity(ActivityTab.ExploreFlagCalls), {}, { q: flagCallsQuery(source) }).url
        )
        await expectLogic(logic).toFinishAllListeners()

        const pinned = logic.values.query.source
        expect(pinned.event).toEqual('$feature_flag_called')
        expect(pinned).not.toHaveProperty('events')
        expect(pinned).not.toHaveProperty('actionId')
        expect(pinned).not.toHaveProperty('actionSteps')
        expect(pinned).not.toHaveProperty('source')
    })

    it('shows the default list for a URL query that is not an events list', async () => {
        const sessionsQuery: Node = {
            kind: NodeKind.DataTableNode,
            source: { kind: NodeKind.SessionsQuery, select: ['session_id'] },
        } as DataTableNode

        router.actions.push(combineUrl(urls.activity(ActivityTab.ExploreFlagCalls), {}, { q: sessionsQuery }).url)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.query).toEqual(logic.values.defaultQuery)
    })

    test.each<[string, FlagEvaluationsModeEnumApi, boolean, string | undefined, boolean]>([
        ['the default range', FlagEvaluationsModeEnumApi.Number2, true, '-24h', false],
        ['a range inside the retention window', FlagEvaluationsModeEnumApi.Number2, true, '-30d', false],
        ['a range older than the retention window', FlagEvaluationsModeEnumApi.Number2, true, '-180d', true],
        ['all time', FlagEvaluationsModeEnumApi.Number1, false, 'all', true],
        ['no start', FlagEvaluationsModeEnumApi.Number2, true, undefined, false],
        ['all time on the events mode', FlagEvaluationsModeEnumApi.Number0, false, 'all', false],
        ['all time on native JSON events with the events mode', FlagEvaluationsModeEnumApi.Number0, true, 'all', true],
    ])('decides whether the retention note shows for %s', (_name, mode, onlyInFlagEvaluations, after, expected) => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            flag_evaluations_mode: mode,
            flag_calls_only_in_flag_evaluations: onlyInFlagEvaluations,
        })

        logic.actions.setQuery(flagCallsQuery({ after }))

        expect(logic.values.reachesPastRetention).toBe(expected)
    })
})
