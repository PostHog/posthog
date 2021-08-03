import { infiniteListLogic } from './infiniteListLogic'
import { BuiltLogic } from 'kea'
import { waitForAction } from 'kea-waitfor'
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

    describe('values', () => {
        it('has proper defaults', () => {
            expect(logic.values).toMatchSnapshot()
        })
    })

    describe('loaders', () => {
        describe('remoteItems', () => {
            it('loads initial items on mount', async () => {
                expect(logic.values.remoteItems.results.length).toEqual(56)
            })

            it('setting search query filters events', async () => {
                logic.actions.setSearchQuery('event')
                expect(logic.values.searchQuery).toEqual('event')

                await waitForAction(logic.actions.loadRemoteItemsSuccess)
                expect(logic.values.remoteItems.results.length).toEqual(3)
                expect(logic.values.remoteItems).toMatchSnapshot()
            })
        })
    })

    describe('reducers', () => {
        describe('index', () => {
            it('is set via setIndex', async () => {
                expect(logic.values.index).toEqual(0)
                logic.actions.setIndex(1)
                expect(logic.values.index).toEqual(1)
            })

            it('can go up and down', async () => {
                expect(logic.values.remoteItems.results.length).toEqual(56)

                logic.actions.moveUp()
                expect(logic.values.index).toEqual(55)

                logic.actions.moveUp()
                expect(logic.values.index).toEqual(54)

                logic.actions.moveDown()
                expect(logic.values.index).toEqual(55)

                logic.actions.moveDown()
                expect(logic.values.index).toEqual(0)

                logic.actions.moveDown()
                expect(logic.values.index).toEqual(1)
            })
        })
    })

    describe('actions', () => {
        describe('selectSelected', () => {
            it('actually selects the selected', async () => {
                expect(logic.values.selectedItem).toEqual(expect.objectContaining({ name: 'event1' }))

                logic.actions.selectItem = jest.fn()
                logic.actions.selectSelected()

                expect(logic.actions.selectItem).toHaveBeenCalledWith(
                    'events',
                    'event1',
                    expect.objectContaining({ name: 'event1' })
                )
            })
        })
    })
})
