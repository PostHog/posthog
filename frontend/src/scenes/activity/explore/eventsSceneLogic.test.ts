import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { HOGQL_COLUMNS_KEY } from '~/queries/nodes/DataTable/defaultEventsQuery'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ActivityTab, TeamType } from '~/types'

import { eventsSceneLogic } from './eventsSceneLogic'

describe('eventsSceneLogic', () => {
    let logic: ReturnType<typeof eventsSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/query': () => [200, { results: [] }],
            },
            patch: {
                '/api/environments/:team_id': () => [200, { ...MOCK_DEFAULT_TEAM, live_events_columns: null }],
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

    it('flags the project default view so the error state can offer a recovery action', async () => {
        // A saved column that no longer resolves is what dead-ends the page; the CTA must key off
        // the fact that the live query is the project default, not off the specific error.
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            live_events_columns: [HOGQL_COLUMNS_KEY, 'session_id'],
        } as TeamType)

        await expectLogic(logic).toMatchValues({ onProjectDefaultColumns: true })
    })

    it('resetProjectDefaultColumns clears the saved columns and shows the PostHog default view', async () => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            live_events_columns: [HOGQL_COLUMNS_KEY, 'session_id'],
        } as TeamType)

        await expectLogic(logic, () => {
            logic.actions.resetProjectDefaultColumns()
        }).toDispatchActions([
            (action) =>
                action.type === teamLogic.actionTypes.updateCurrentTeam && action.payload.live_events_columns === null,
            'setQuery',
        ])

        expect(logic.values.query).toEqual(getDefaultEventsSceneQuery())
        expect(logic.values.onProjectDefaultColumns).toBe(false)
    })
})
