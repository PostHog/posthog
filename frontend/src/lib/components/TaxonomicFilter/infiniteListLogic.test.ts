import { infiniteListLogic } from './infiniteListLogic'
import { BuiltLogic } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { infiniteListLogicType } from 'lib/components/TaxonomicFilter/infiniteListLogicType'
import { mockAPIGet } from 'lib/api.mock'
import { initKeaTestLogic } from '~/test/utils'
import { mockEventDefinitions } from '~/test/mocks'

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
        waitFor: 'loadRemoteItemsSuccess',
        onLogic: (l) => (logic = l),
    })

    it('calls loadRemoteItems on mount', () => {
        expectLogic(logic)
            .toDispatch(['loadRemoteItems', 'loadRemoteItemsSuccess'])
            .toMatchValues({ remoteItems: { results: expect.arrayContaining([{ name: expect.any(String) }]) } })
    })

    it('setting search query filters events', async () => {
        expectLogic(logic, () => logic.actions.setSearchQuery('event'))
            .toDispatch(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
            .toMatchValues({ searchQuery: 'event', remoteItems: { results: Array(3) } })
    })

    describe('index', async () => {
        it('is set via setIndex', async () => {
            expectLogic(logic).toMatchValues({ index: 0 })
            expectLogic(logic, () => logic.actions.setIndex(1)).toHaveValues({ index: 1 })
        })

        it('can go up and down', async () => {
            expectLogic(logic).toMatchValues({ index: 0, remoteItems: Array(56) })
            expectLogic(logic, () => logic.actions.moveUp()).toHaveValues({ index: 55 })
            expectLogic(logic, () => logic.actions.moveUp()).toHaveValues({ index: 54 })
            expectLogic(logic, () => logic.actions.moveDown()).toHaveValues({ index: 55 })
            expectLogic(logic, () => logic.actions.moveDown()).toHaveValues({ index: 0 })
            expectLogic(logic, () => logic.actions.moveDown()).toHaveValues({ index: 1 })
            expectLogic(logic, () => logic.actions.moveUp()).toHaveValues({ index: 0 })
        })
    })

    it('selects the selected item', async () => {
        expectLogic(logic).toMatchValues({ selectedItem: expect.objectContaining({ name: 'event1' }) })

        expectLogic(logic, () => logic.actions.selectSelected()).toDispatch([
            logic.actionCreators.selectSelected(),
            logic.actionCreators.selectItem(
                TaxonomicFilterGroupType.Events,
                'event1',
                expect.objectContaining({ name: 'event1' })
            ),
        ])
    })
})
