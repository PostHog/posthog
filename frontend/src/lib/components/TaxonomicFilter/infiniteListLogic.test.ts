import { infiniteListLogic } from './infiniteListLogic'
import { BuiltLogic } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { infiniteListLogicType } from 'lib/components/TaxonomicFilter/infiniteListLogicType'
import { mockAPIGet } from 'lib/api.mock'
import { initKeaTestLogic } from '~/test/kea-utils'
import { mockEventDefinitions } from '~/test/mocks'
import { expectLogic } from '~/test/kea-utils'

jest.mock('lib/api')

describe('infiniteListLogic verbose version', () => {
    let logic: BuiltLogic<infiniteListLogicType>

    mockAPIGet(async ({ pathname, searchParams }) => {
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
        // waitFor: 'loadRemoteItemsSuccess',
        onLogic: (l) => (logic = l),
    })

    it('calls loadRemoteItems on mount', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadRemoteItems', 'loadRemoteItemsSuccess'])
            .toMatchValues({ remoteItems: { results: expect.arrayContaining([{ name: expect.any(String) }]) } })
            .run()
    })

    it('setting search query filters events (verbose)', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSearchQuery('event')
        })
            .toDispatchActions([logic.actionCreators.setSearchQuery('event')])
            .toDispatchActions(['loadRemoteItems'])
            .toMatchValues({
                searchQuery: 'event',
                remoteItems: expect.objectContaining({ results: expect.any(Array) }),
                remoteItemsLoading: true,
            })
            // works until the async part here
            .toDispatchActions(['loadRemoteItemsSuccess'])
            .toMatchValues({
                searchQuery: 'event',
                remoteItems: { results: expect.any(Array) },
                remoteItemsLoading: false,
            })
            .run()
    })

    it('setting search query filters events (succint)', async () => {
        await expectLogic(logic, () => logic.actions.setSearchQuery('event'))
            .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
            .toMatchValues({ searchQuery: 'event', remoteItems: expect.objectContaining({ results: Array(3) }) })
            .run()
    })

    describe('index', () => {
        it('is set via setIndex', async () => {
            await expectLogic(logic).toDispatchActions(['loadRemoteItemsSuccess']).run()
            expectLogic(logic).toMatchValues({ index: 0 })
            expectLogic(logic, () => logic.actions.setIndex(1)).toMatchValues({ index: 1 })
        })

        it('can go up and down', async () => {
            await expectLogic(logic).toDispatchActions(['loadRemoteItems', 'loadRemoteItemsSuccess']).run()
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
