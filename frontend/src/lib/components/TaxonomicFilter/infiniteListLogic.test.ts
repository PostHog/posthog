import { infiniteListLogic } from './infiniteListLogic'
import { BuiltLogic } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { infiniteListLogicType } from 'lib/components/TaxonomicFilter/infiniteListLogicType'
import { mockAPIGet } from 'lib/api.mock'
import { initKeaTestLogic, testLogic } from '~/test/utils'
import { mockEventDefinitions } from '~/test/mocks'

jest.mock('lib/api')

describe('infiniteListLogic', () => {
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

    describe('with remote datasource', () => {
        let logic: BuiltLogic<infiniteListLogicType>
        initKeaTestLogic({
            logic: infiniteListLogic,
            props: {
                taxonomicFilterLogicKey: 'testList',
                listGroupType: TaxonomicFilterGroupType.Events,
            },
            onLogic: (l) => (logic = l),
        })

        beforeEach(async () => {
            console.log('wait 1')
            await testLogic(logic, ({ actions }, { waitFor }) => [() => waitFor(actions.loadRemoteItemsSuccess)])
            console.log('wait 2')
        })

        describe('loads remote items', () => {
            it('when setting the search query', async () => {
                await testLogic(logic, ({ actions }, { waitFor }) => [
                    () => actions.setSearchQuery('event'),
                    () => waitFor(actions.loadRemoteItemsSuccess),
                ])
            })
        })

        describe('sets search index', () => {
            it('with setIndex', async () => {
                await testLogic(logic, ({ actions }) => [() => actions.setIndex(1)])
            })

            it('can go up and down', async () => {
                await testLogic(logic, ({ actions }) => [
                    () => actions.moveUp(),
                    () => actions.moveUp(),
                    () => actions.moveDown(),
                    () => actions.moveDown(),
                    () => actions.moveDown(),
                ])
            })
        })

        describe('select selected', () => {
            it('changes selected item', async () => {
                await testLogic(logic, ({ actions }, { waitFor }) => [
                    () => actions.selectSelected(),
                    () => waitFor(actions.selectItem),
                ])
            })
        })
    })
})
