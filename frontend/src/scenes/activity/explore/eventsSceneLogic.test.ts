import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { DataTableNode, EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ActivityTab } from '~/types'

import { eventsSceneLogic } from './eventsSceneLogic'

const OUTSIDE_WINDOW_TIMESTAMP = '2024-03-01T10:00:00Z'

function queryWith(source: Partial<EventsQuery>): DataTableNode {
    return {
        kind: NodeKind.DataTableNode,
        full: true,
        source: {
            kind: NodeKind.EventsQuery,
            select: ['*', 'event', 'person', 'timestamp'],
            after: '-1h',
            ...source,
        } as EventsQuery,
    }
}

/** Answers the empty-state probes: `rowsFor` decides which of the two probe queries finds a match. */
function useProbeQueryMocks(rowsFor: (source: EventsQuery) => boolean): void {
    useMocks({
        post: {
            '/api/environments/:team_id/query/:kind': async (info) => {
                const { query } = (await info.request.json()) as { query: DataTableNode['source'] }
                const source = query as EventsQuery
                return [200, { results: rowsFor(source) ? [[OUTSIDE_WINDOW_TIMESTAMP]] : [] }]
            },
        },
    })
}

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

    it('points an empty result at events outside the time range, and widens to them', async () => {
        useProbeQueryMocks((source) => source.after === '-90d')
        logic.actions.setQuery(queryWith({ event: '$pageview' }))

        logic.actions.probeForHiddenEvents()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.hiddenEventsProbe).toEqual({
            latestOutsideWindow: OUTSIDE_WINDOW_TIMESTAMP,
            hiddenByTestAccountFilter: false,
        })

        logic.actions.widenToHiddenEvents()
        const source = (logic.values.query as DataTableNode).source as EventsQuery
        expect(dayjs(source.after).toISOString()).toEqual(
            dayjs(OUTSIDE_WINDOW_TIMESTAMP).subtract(1, 'hour').toISOString()
        )
        expect(source.before).toBeUndefined()
        expect(source.event).toEqual('$pageview')
    })

    it('points an empty result at the test account filter, and turns it off', async () => {
        useProbeQueryMocks((source) => source.filterTestAccounts === false)
        logic.actions.setQuery(queryWith({ filterTestAccounts: true }))

        logic.actions.probeForHiddenEvents()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.hiddenEventsProbe).toEqual({
            latestOutsideWindow: null,
            hiddenByTestAccountFilter: true,
        })

        logic.actions.dropTestAccountFilter()
        expect(((logic.values.query as DataTableNode).source as EventsQuery).filterTestAccounts).toBe(false)
    })
})
