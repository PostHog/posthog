import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions } from '~/test/mocks'
import { AppContext } from '~/types'

import { infiniteListLogic } from './infiniteListLogic'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'

window.POSTHOG_APP_CONTEXT = {
    current_team: { id: MOCK_TEAM_ID },
    current_project: { id: MOCK_TEAM_ID },
} as unknown as AppContext

describe('InfiniteSelectResults - CategoryPill logic mounting', () => {
    let logic: ReturnType<typeof taxonomicFilterLogic.build>

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey: 'test-category-pill',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': (res) => {
                    const search = res.url.searchParams.get('search')
                    const results = search
                        ? mockEventDefinitions.filter((e) => e.name.includes(search))
                        : mockEventDefinitions
                    return [200, { results, count: results.length }]
                },
            },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()

        logic = taxonomicFilterLogic(taxonomicFilterLogicProps)
        logic.mount()

        // Mount infiniteListLogics for each group type (this is what BindLogic does in CategoryPill)
        for (const listGroupType of taxonomicFilterLogicProps.taxonomicGroupTypes) {
            infiniteListLogic({ ...taxonomicFilterLogicProps, listGroupType }).mount()
        }
    })

    it('infiniteListLogic is properly mounted for each group type when using BindLogic pattern', async () => {
        // The fix ensures that CategoryPill wraps its content with BindLogic, which properly mounts
        // the infiniteListLogic for each group type. Without this, KEA throws "Can not find path" errors.

        // Verify all infiniteListLogics are mounted (this simulates what BindLogic achieves)
        await expectLogic(logic).toMount([
            infiniteListLogic({ ...taxonomicFilterLogicProps, listGroupType: TaxonomicFilterGroupType.Events }),
            infiniteListLogic({ ...taxonomicFilterLogicProps, listGroupType: TaxonomicFilterGroupType.Actions }),
        ])

        // Verify logic is accessible and has expected structure
        const eventsLogic = infiniteListLogic({
            ...taxonomicFilterLogicProps,
            listGroupType: TaxonomicFilterGroupType.Events,
        })
        expect(eventsLogic.isMounted()).toBe(true)
        expect(eventsLogic.values.listGroupType).toBe(TaxonomicFilterGroupType.Events)

        const actionsLogic = infiniteListLogic({
            ...taxonomicFilterLogicProps,
            listGroupType: TaxonomicFilterGroupType.Actions,
        })
        expect(actionsLogic.isMounted()).toBe(true)
        expect(actionsLogic.values.listGroupType).toBe(TaxonomicFilterGroupType.Actions)
    })

    it('infiniteListLogic can access values after being mounted via BindLogic pattern', async () => {
        // This test verifies that the logic can properly access its selectors without errors
        // The original bug caused "Can not find path" errors when trying to access these values

        const eventsLogic = infiniteListLogic({
            ...taxonomicFilterLogicProps,
            listGroupType: TaxonomicFilterGroupType.Events,
        })

        // These are the values that CategoryPillContent accesses via useValues(infiniteListLogic)
        // Without proper BindLogic mounting, accessing these would throw KEA errors
        await expectLogic(eventsLogic).toMatchValues({
            listGroupType: TaxonomicFilterGroupType.Events,
            hasRemoteDataSource: true,
        })

        // Verify we can access result counts without errors
        expect(typeof eventsLogic.values.totalResultCount).toBe('number')
        expect(typeof eventsLogic.values.totalListCount).toBe('number')
        expect(typeof eventsLogic.values.isLoading).toBe('boolean')
    })

    it('multiple infiniteListLogics with different group types can coexist', async () => {
        // The fix ensures each CategoryPill has its own properly-bound infiniteListLogic instance
        // This prevents conflicts between different group types

        const eventsLogic = infiniteListLogic({
            ...taxonomicFilterLogicProps,
            listGroupType: TaxonomicFilterGroupType.Events,
        })
        const actionsLogic = infiniteListLogic({
            ...taxonomicFilterLogicProps,
            listGroupType: TaxonomicFilterGroupType.Actions,
        })

        // Both should be mounted and have distinct group types
        expect(eventsLogic.isMounted()).toBe(true)
        expect(actionsLogic.isMounted()).toBe(true)
        expect(eventsLogic.values.listGroupType).not.toBe(actionsLogic.values.listGroupType)

        // The logics should have different keys
        expect(eventsLogic.pathString).toContain('events')
        expect(actionsLogic.pathString).toContain('actions')
    })
})
