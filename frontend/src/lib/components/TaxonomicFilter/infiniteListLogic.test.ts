import { infiniteListLogic } from './infiniteListLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic, partial } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions } from '~/test/mocks'
import { teamLogic } from 'scenes/teamLogic'
import { AppContext } from '~/types'

jest.mock('lib/api')

window.POSTHOG_APP_CONTEXT = { current_team: { id: MOCK_TEAM_ID } } as unknown as AppContext

describe('infiniteListLogic', () => {
    let logic: ReturnType<typeof infiniteListLogic.build>

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
    })

    describe('events with remote data source', () => {
        beforeEach(() => {
            logic = infiniteListLogic({
                taxonomicFilterLogicKey: 'testList',
                listGroupType: TaxonomicFilterGroupType.Events,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
            })
            logic.mount()
        })

        it('calls loadRemoteItems on mount', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    remoteItems: partial({
                        results: partial([partial({ name: 'event1' })]),
                    }),
                })
        })

        it('setting search query filters events', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('event')
            })
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    searchQuery: 'event',
                    remoteItems: partial({
                        count: 3,
                        results: partial([partial({ name: 'event1' })]),
                    }),
                })
        })

        it('setting search query loads remote items', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('event')
            })
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems'])
                .toMatchValues({
                    searchQuery: 'event',
                    remoteItems: partial({
                        count: 0,
                    }),
                    remoteItemsLoading: true,
                })
                .toDispatchActions(['loadRemoteItemsSuccess', 'infiniteListResultsReceived'])
                .toMatchValues({
                    searchQuery: 'event',
                    remoteItems: partial({
                        count: 3,
                        results: partial([partial({ name: 'event1' })]),
                    }),
                    remoteItemsLoading: false,
                })
        })

        describe('index', () => {
            it('is set via setIndex', async () => {
                await expectLogic(logic).toDispatchActions(['loadRemoteItemsSuccess']) // wait for data
                expectLogic(logic).toMatchValues({ index: 0, remoteItems: partial({ count: 56 }) })
                expectLogic(logic, () => logic.actions.setIndex(1)).toMatchValues({
                    remoteItems: partial({ count: 56 }),
                    index: 1,
                })
            })

            it('can go up and down', async () => {
                await expectLogic(logic).toDispatchActions(['loadRemoteItemsSuccess']) // wait for data
                expectLogic(logic).toMatchValues({ index: 0, remoteItems: partial({ count: 56 }) })
                expectLogic(logic, () => logic.actions.moveUp()).toMatchValues({ index: 55 })
                expectLogic(logic, () => logic.actions.moveUp()).toMatchValues({ index: 54 })
                expectLogic(logic, () => logic.actions.moveDown()).toMatchValues({ index: 55 })
                expectLogic(logic, () => logic.actions.moveDown()).toMatchValues({ index: 0 })
                expectLogic(logic, () => logic.actions.moveDown()).toMatchValues({ index: 1 })
                expectLogic(logic, () => logic.actions.moveUp()).toMatchValues({ index: 0 })
            })
        })

        it('selects the selected item', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadRemoteItemsSuccess'])
                .toMatchValues({ selectedItem: partial({ name: 'event1' }) })

            await expectLogic(logic, () => {
                logic.actions.selectSelected()
            }).toDispatchActions([
                logic.actionCreators.selectSelected(),
                ({ type, payload }) =>
                    type === logic.actionTypes.selectItem &&
                    payload.group.type === TaxonomicFilterGroupType.Events &&
                    payload.value === 'event1' &&
                    payload.item.name === 'event1',
            ])
        })
    })

    describe('with optionsFromProp', () => {
        beforeEach(() => {
            logic = infiniteListLogic({
                taxonomicFilterLogicKey: 'testList',
                listGroupType: TaxonomicFilterGroupType.Wildcards,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
                optionsFromProp: {
                    wildcard: [{ name: 'first' }, { name: 'second' }],
                },
            })
            logic.mount()
        })

        it('doesnt call loadRemoteItems on mount, loads results locally', async () => {
            await expectLogic(logic)
                .toDispatchActions([])
                .toMatchValues({
                    results: partial([partial({ name: 'first' }), partial({ name: 'second' })]),
                })
        })
    })
})
