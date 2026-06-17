import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ActivityTab } from '~/types'

import { eventsSceneLogic } from './eventsSceneLogic'

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
})
