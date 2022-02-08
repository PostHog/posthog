import { infiniteListLogic } from './infiniteListLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions } from '~/test/mocks'
import { teamLogic } from 'scenes/teamLogic'
import { AppContext } from '~/types'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { groupsModel } from '~/models/groupsModel'
import { actionsModel } from '~/models/actionsModel'

jest.mock('lib/api')

window.POSTHOG_APP_CONTEXT = { current_team: { id: MOCK_TEAM_ID } } as unknown as AppContext

describe('taxonomicFilterLogic', () => {
    let logic: ReturnType<typeof taxonomicFilterLogic.build>

    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === `api/projects/${MOCK_TEAM_ID}/event_definitions`) {
            const results = searchParams.search
                ? mockEventDefinitions.filter((e) => e.name.includes(searchParams.search))
                : mockEventDefinitions
            return {
                results,
                count: results.length,
            }
        }
    })

    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
        actionsModel.mount()
        groupsModel.mount()
    })

    beforeEach(() => {
        const logicProps: TaxonomicFilterLogicProps = {
            taxonomicFilterLogicKey: 'testList',
            taxonomicGroupTypes: [
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.Actions,
                TaxonomicFilterGroupType.Elements,
            ],
        }
        logic = taxonomicFilterLogic(logicProps)
        logic.mount()

        // does not automatically mount these, but needs them
        for (const listGroupType of logicProps.taxonomicGroupTypes) {
            infiniteListLogic({ ...logicProps, listGroupType }).mount()
        }
    })

    it('mounts all infinite list logics', async () => {
        await expectLogic(logic).toMount([
            infiniteListLogic({ ...logic.props, listGroupType: TaxonomicFilterGroupType.Events }),
            infiniteListLogic({ ...logic.props, listGroupType: TaxonomicFilterGroupType.Actions }),
            infiniteListLogic({ ...logic.props, listGroupType: TaxonomicFilterGroupType.Elements }),
        ])
        expect(
            infiniteListLogic({ ...logic.props, listGroupType: TaxonomicFilterGroupType.Cohorts }).isMounted()
        ).toBeFalsy()
    })

    it('keeps totalCounts in sync', async () => {
        await expectLogic(logic)
            .toMatchValues({
                totalCounts: {
                    [TaxonomicFilterGroupType.Events]: 0,
                    [TaxonomicFilterGroupType.Actions]: 0,
                    [TaxonomicFilterGroupType.Elements]: 4,
                },
            })
            .toDispatchActions(['infiniteListResultsReceived'])
            .delay(1)
            .clearHistory()
            .toMatchValues({
                totalCounts: {
                    [TaxonomicFilterGroupType.Events]: 56,
                    [TaxonomicFilterGroupType.Actions]: 0, // not mocked
                    [TaxonomicFilterGroupType.Elements]: 4,
                },
            })
    })

    it('setting search query filters events', async () => {
        // load the initial results
        await expectLogic(logic).toDispatchActionsInAnyOrder([
            'infiniteListResultsReceived',
            'infiniteListResultsReceived',
        ])

        await expectLogic(logic, () => {
            logic.actions.setSearchQuery('event')
        })
            .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived'])
            .toMatchValues({
                searchQuery: 'event',
                activeTab: TaxonomicFilterGroupType.Events,
                totalCounts: {
                    [TaxonomicFilterGroupType.Events]: 3,
                    [TaxonomicFilterGroupType.Actions]: 0,
                    [TaxonomicFilterGroupType.Elements]: 0,
                },
            })

        await expectLogic(logic, () => {
            logic.actions.setSearchQuery('selector')
        })
            .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived'])
            .delay(1)
            .clearHistory()
            .toMatchValues({
                searchQuery: 'selector',
                activeTab: TaxonomicFilterGroupType.Elements, // tab changed!
                totalCounts: {
                    [TaxonomicFilterGroupType.Events]: 0,
                    [TaxonomicFilterGroupType.Actions]: 0,
                    [TaxonomicFilterGroupType.Elements]: 1,
                },
            })

        await expectLogic(logic, () => {
            logic.actions.setSearchQuery('this is not found')
        })
            .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived'])
            .delay(1)
            .clearHistory()
            .toMatchValues({
                searchQuery: 'this is not found',
                activeTab: TaxonomicFilterGroupType.Elements, // no change
                totalCounts: {
                    [TaxonomicFilterGroupType.Events]: 0,
                    [TaxonomicFilterGroupType.Actions]: 0,
                    [TaxonomicFilterGroupType.Elements]: 0,
                },
            })

        await expectLogic(logic, () => {
            logic.actions.setSearchQuery('')
        })
            .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived'])
            .delay(1)
            .clearHistory()
            .toMatchValues({
                searchQuery: '',
                activeTab: TaxonomicFilterGroupType.Elements, // no change
                totalCounts: {
                    [TaxonomicFilterGroupType.Events]: 56,
                    [TaxonomicFilterGroupType.Actions]: 0,
                    [TaxonomicFilterGroupType.Elements]: 4,
                },
            })

        // move right, skipping Actions
        await expectLogic(logic, () => logic.actions.tabRight()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.Events,
        })
        await expectLogic(logic, () => logic.actions.tabRight()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.Elements,
        })

        // move left, skipping Actions
        await expectLogic(logic, () => logic.actions.tabLeft()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.Events,
        })
        await expectLogic(logic, () => logic.actions.tabLeft()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.Elements,
        })

        // open remote items tab after loading
        await expectLogic(logic, () => {
            logic.actions.setSearchQuery('event')
        })
            .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived'])
            .delay(1)
            .clearHistory()
            .toMatchValues({
                searchQuery: 'event',
                activeTab: TaxonomicFilterGroupType.Events, // changed!
                totalCounts: {
                    [TaxonomicFilterGroupType.Events]: 3,
                    [TaxonomicFilterGroupType.Actions]: 0,
                    [TaxonomicFilterGroupType.Elements]: 0,
                },
            })
    })
})
