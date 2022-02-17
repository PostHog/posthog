import { infiniteListLogic } from './infiniteListLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic, partial } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockEventPropertyDefinitions } from '~/test/mocks'
import { teamLogic } from 'scenes/teamLogic'
import { AppContext, EventDefinition, PropertyDefinition } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

jest.mock('lib/api')

window.POSTHOG_APP_CONTEXT = { current_team: { id: MOCK_TEAM_ID } } as unknown as AppContext

describe('infiniteListLogic', () => {
    let logic: ReturnType<typeof infiniteListLogic.build>

    mockAPI(async ({ pathname, searchParams }) => {
        const isEventDefinitions = pathname === `api/projects/${MOCK_TEAM_ID}/event_definitions`
        const isPropertyDefinitions = pathname === `api/projects/${MOCK_TEAM_ID}/property_definitions`

        if (isEventDefinitions || isPropertyDefinitions) {
            // Type defaults to `EventDefinition[] | PropertyDefinition[]`,
            // which does not type well with `.filter(e => ...)` below
            let results: (EventDefinition | PropertyDefinition)[] = isEventDefinitions
                ? mockEventDefinitions
                : mockEventPropertyDefinitions

            if (searchParams.search) {
                results = results.filter((e) => e.name.includes(searchParams.search))
            }
            if (isPropertyDefinitions && searchParams.is_event_property !== undefined) {
                results = results.filter(
                    (e: PropertyDefinition) => e.is_event_property === searchParams.is_event_property
                )
            }

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

    describe('expandable list of event properties', () => {
        beforeEach(() => {
            const flag = FEATURE_FLAGS.UNSEEN_EVENT_PROPERTIES
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([flag], { [flag]: true })
            logic = infiniteListLogic({
                taxonomicFilterLogicKey: 'testList',
                listGroupType: TaxonomicFilterGroupType.EventProperties,
                eventNames: ['$pageview'],
                taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
            })
            logic.mount()
        })

        it('setting search query filters events', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('browser')
            })
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    searchQuery: 'browser',
                    isExpandable: true,
                    isExpanded: false,
                    isExpandableButtonSelected: false,
                    totalCount: 1,
                    totalListCount: 2, // 1 + 1 for "expand list" button
                    expandedCount: 2,
                    remoteItems: partial({
                        count: 1,
                        expandedCount: 2,
                        results: partial([partial({ name: '$browser', is_event_property: true })]),
                    }),
                })

            await expectLogic(logic, () => {
                logic.actions.expand()
            })
                .toDispatchActions(['expand', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    searchQuery: 'browser',
                    isExpandable: false,
                    isExpanded: true,
                    isExpandableButtonSelected: false,
                    totalCount: 2,
                    totalListCount: 2,
                    expandedCount: 0,
                    remoteItems: partial({
                        count: 2,
                        expandedCount: undefined,
                        results: partial([
                            partial({ name: '$browser', is_event_property: true }),
                            partial({ name: 'browser_no_dollar_not_on_event', is_event_property: false }),
                        ]),
                    }),
                })

            // remains extended after extending once
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('bro')
            })
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    searchQuery: 'bro',
                    isExpandable: false,
                    isExpanded: true,
                    isExpandableButtonSelected: false,
                    totalCount: 2,
                    totalListCount: 2,
                    expandedCount: 0,
                    remoteItems: partial({
                        count: 2,
                        expandedCount: undefined,
                        results: partial([
                            partial({ name: '$browser', is_event_property: true }),
                            partial({ name: 'browser_no_dollar_not_on_event', is_event_property: false }),
                        ]),
                    }),
                })
        })

        it('moving up selects expansion button', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('browser')
            })
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    searchQuery: 'browser',
                    isExpandable: true,
                    isExpanded: false,
                    isExpandableButtonSelected: false,
                    totalCount: 1,
                    totalListCount: 2, // 1 + 1 for "expand list" button
                    expandedCount: 2,
                    index: 0,
                    remoteItems: partial({
                        count: 1,
                        expandedCount: 2,
                        results: partial([partial({ name: '$browser', is_event_property: true })]),
                    }),
                })

            await expectLogic(logic, () => {
                logic.actions.moveUp()
            }).toMatchValues({ index: 1, isExpandableButtonSelected: true })

            await expectLogic(logic, () => {
                logic.actions.selectSelected()
            })
                .toDispatchActions(['selectSelected', 'expand', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    searchQuery: 'browser',
                    isExpandable: false,
                    isExpanded: true,
                    isExpandableButtonSelected: false,
                    totalCount: 2,
                    totalListCount: 2,
                    expandedCount: 0,
                    remoteItems: partial({
                        count: 2,
                        expandedCount: undefined,
                        results: partial([
                            partial({ name: '$browser', is_event_property: true }),
                            partial({ name: 'browser_no_dollar_not_on_event', is_event_property: false }),
                        ]),
                    }),
                })
        })
    })
})
