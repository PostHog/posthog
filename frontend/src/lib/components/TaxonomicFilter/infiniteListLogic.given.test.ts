import given from 'given2'
import { infiniteListLogic } from './infiniteListLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { waitForAction } from 'kea-waitfor'
import { mockAPIGet } from 'lib/api.mock'
import { initKeaTestLogic } from '~/test/test-utils'
import { mockEventDefinitions } from '~/test/mocks'

jest.mock('lib/api')

describe('infiniteListLogic with given', () => {
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
        onLogic: (logic) => (given.logic = logic), // given('logic', () => logic) doesn't work here
    })

    given('searchQuery', () => () => given.logic.values.searchQuery)

    describe('values', () => {
        given('subject', () => () => given.logic.values)

        it('has proper defaults', async () => {
            expect(given.subject()).toMatchSnapshot()
        })
    })

    describe('loaders', () => {
        describe('remoteItems', () => {
            given('subject', () => () => given.logic.values.remoteItems)

            it('loads initial items on mount', async () => {
                expect(given.subject()).toMatchSnapshot()
            })

            it('setting search query filters events', async () => {
                given.logic.actions.setSearchQuery('event')
                expect(given.searchQuery()).toEqual('event')

                await waitForAction(given.logic.actionTypes.loadRemoteItemsSuccess)
                expect(given.subject()).toMatchSnapshot()
            })
        })
    })

    describe('loaders', () => {
        describe('remoteItems', () => {
            given('subject', () => () => given.logic.values.remoteItems)
            given('resultCount', () => () => given.logic.values.remoteItems.results.length)

            it('loads initial items on mount', async () => {
                expect(given.resultCount()).toEqual(206)
            })

            it('setting search query filters events', async () => {
                given.logic.actions.setSearchQuery('event')
                expect(given.searchQuery()).toEqual('event')

                await waitForAction(given.logic.actionTypes.loadRemoteItemsSuccess)
                expect(given.resultCount()).toEqual(3)
                expect(given.subject()).toMatchSnapshot()
            })
        })
    })
})
