import { infiniteListLogic } from './infiniteListLogic'
import { BuiltLogic } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { infiniteListLogicType } from 'lib/components/TaxonomicFilter/infiniteListLogicType'
import { mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic, partial } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockPropertyDefinitions } from '~/test/mocks'
import { teamLogic } from 'scenes/teamLogic'
import { AppContext } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

jest.mock('lib/api')

window.POSTHOG_APP_CONTEXT = { current_team: { id: MOCK_TEAM_ID } } as unknown as AppContext

const propertyDefinitions = mockPropertyDefinitions([
    '$performance_raw',
    '$performance_page_loaded',
    '$performance_not_on_denylist',
])

describe('infiniteListLogic', () => {
    let logic: BuiltLogic<infiniteListLogicType>

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
        if (pathname === `api/projects/${MOCK_TEAM_ID}/property_definitions`) {
            const results = searchParams.search
                ? propertyDefinitions.filter((e) => e.name.includes(searchParams.search))
                : propertyDefinitions
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

    describe('when loading property definitions', () => {
        beforeEach(() => {
            logic = infiniteListLogic({
                taxonomicFilterLogicKey: 'testPropDefList',
                listGroupType: TaxonomicFilterGroupType.EventProperties,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
            })
            logic.mount()
        })

        it('filters performance properties if APM flag is off', async () => {
            const variants = {}
            variants[FEATURE_FLAGS.APM] = false
            featureFlagLogic.actions.setFeatureFlags([], variants)
            featureFlagLogic.actions.setFeatureFlags([], variants)

            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('$perf')
            })
                .toDispatchActions(['loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    items: {
                        count: 1,
                        queryChanged: true,
                        results: [
                            {
                                description: '2',
                                id: 'uuid-2-foobar',
                                name: '$performance_not_on_denylist',
                                query_usage_30_day: null,
                                volume_30_day: null,
                            },
                        ],
                        searchQuery: '$perf',
                    },
                })
        })

        it('does not filter performance properties if APM flag is on', async () => {
            const variants = {}
            variants[FEATURE_FLAGS.APM] = true
            featureFlagLogic.actions.setFeatureFlags([], variants)
            featureFlagLogic.actions.setFeatureFlags([], variants)

            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('$perfo') //slightly change search query to avoid the cache
            })
                .toDispatchActions(['loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    items: {
                        count: 3,
                        queryChanged: true,
                        results: propertyDefinitions,
                        searchQuery: '$perfo',
                    },
                })
        })
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
