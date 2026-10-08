import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { DataTableNode, EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ActivityTab } from '~/types'

import { FlagCallsNote, eventsSceneLogic } from './eventsSceneLogic'

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

    it('picks up a drill-down events query from the #q= hash', async () => {
        // The "View events" persons-modal action deep-links here with an events DataTableNode in the hash.
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'person', 'timestamp'],
                event: '$pageview',
                after: 'all',
            } as any,
            full: true,
        }

        router.actions.push(combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: query }).url)

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.query).toEqual(query)
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
})
