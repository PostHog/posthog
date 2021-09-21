import { infiniteListLogic } from './infiniteListLogic'
import { BuiltLogic } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { infiniteListLogicType } from 'lib/components/TaxonomicFilter/infiniteListLogicType'
import { mockAPI } from 'lib/api.mock'
import { initKeaTestLogic, expectLogic } from '~/test/kea-test-utils'
import { mockEventDefinitions } from '~/test/mocks'

jest.mock('lib/api')

describe('infiniteListLogic', () => {
    let logic: BuiltLogic<infiniteListLogicType>

    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === 'api/projects/@current/event_definitions') {
            const results = searchParams.search
                ? mockEventDefinitions.filter((e) => e.name.includes(searchParams.search))
                : mockEventDefinitions
            return {
                results,
                count: results.length,
            }
        }
    })

    initKeaTestLogic({
        logic: infiniteListLogic,
        props: {
            taxonomicFilterLogicKey: 'testList',
            listGroupType: TaxonomicFilterGroupType.Events,
        },
        onLogic: (l) => (logic = l),
    })

    it('calls loadRemoteItems on mount', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadRemoteItems', 'loadRemoteItemsSuccess'])
            .toMatchValues({
                remoteItems: expect.objectContaining({
                    results: expect.arrayContaining([expect.objectContaining({ name: 'event1' })]),
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
                remoteItems: expect.objectContaining({
                    count: 3,
                    results: expect.arrayContaining([expect.objectContaining({ name: 'event1' })]),
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
                remoteItems: expect.objectContaining({
                    count: 56, // old values, didn't get success action yet
                }),
                remoteItemsLoading: true,
            })
            .toDispatchActions(['loadRemoteItemsSuccess'])
            .toMatchValues({
                searchQuery: 'event',
                remoteItems: expect.objectContaining({
                    count: 3, // got new results
                    results: expect.arrayContaining([expect.objectContaining({ name: 'event1' })]),
                }),
                remoteItemsLoading: false,
            })
    })

    describe('index', () => {
        it('is set via setIndex', async () => {
            await expectLogic(logic).toDispatchActions(['loadRemoteItemsSuccess']) // wait for data
            expectLogic(logic).toMatchValues({ index: 0, remoteItems: expect.objectContaining({ count: 56 }) })
            expectLogic(logic, () => logic.actions.setIndex(1)).toMatchValues({
                remoteItems: expect.objectContaining({ count: 56 }),
                index: 1,
            })
        })

        it('can go up and down', async () => {
            await expectLogic(logic).toDispatchActions(['loadRemoteItemsSuccess']) // wait for data
            expectLogic(logic).toMatchValues({ index: 0, remoteItems: expect.objectContaining({ count: 56 }) })
            expectLogic(logic, () => logic.actions.moveUp()).toMatchValues({ index: 55 })
            expectLogic(logic, () => logic.actions.moveUp()).toMatchValues({ index: 54 })
            expectLogic(logic, () => logic.actions.moveDown()).toMatchValues({ index: 55 })
            expectLogic(logic, () => logic.actions.moveDown()).toMatchValues({ index: 0 })
            expectLogic(logic, () => logic.actions.moveDown()).toMatchValues({ index: 1 })
            expectLogic(logic, () => logic.actions.moveUp()).toMatchValues({ index: 0 })
        })
    })

    it('selects the selected item', async () => {
        expectLogic(logic).toMatchValues({ selectedItem: expect.objectContaining({ name: 'event1' }) })
        expectLogic(logic, () => logic.actions.selectSelected()).toDispatchActions([
            logic.actionCreators.selectSelected(),
            logic.actionCreators.selectItem(
                TaxonomicFilterGroupType.Events,
                'event1',
                expect.objectContaining({ name: 'event1' })
            ),
        ])
    })
})
