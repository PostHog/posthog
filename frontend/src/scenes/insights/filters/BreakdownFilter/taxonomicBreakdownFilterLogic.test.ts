import { expectLogic } from 'kea-test-utils'

import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { initKeaTests } from '~/test/init'
import { ChartDisplayType, InsightLogicProps } from '~/types'

import * as breakdownLogic from './taxonomicBreakdownFilterLogic'

const { taxonomicBreakdownFilterLogic } = breakdownLogic

const taxonomicGroupFor = (
    type: TaxonomicFilterGroupType,
    groupTypeIndex: number | undefined = undefined
): TaxonomicFilterGroup => ({
    type: type,
    groupTypeIndex: groupTypeIndex,
    name: 'unused in these tests',
    searchPlaceholder: 'unused in these tests',
    getName: () => 'unused in these tests',
    getValue: () => 'unused in these tests',
    getPopoverHeader: () => 'unused in these tests',
})

const updateBreakdownFilter = jest.fn()
const updateDisplay = jest.fn()
const insightProps: InsightLogicProps = { dashboardItemId: 'new' }

const makeProps = (
    overrides: Partial<breakdownLogic.TaxonomicBreakdownFilterLogicProps> & {
        breakdownFilter: breakdownLogic.TaxonomicBreakdownFilterLogicProps['breakdownFilter']
    }
): breakdownLogic.TaxonomicBreakdownFilterLogicProps => ({
    insightProps,
    isTrends: true,
    isFunnels: false,
    updateBreakdownFilter,
    updateDisplay,
    ...overrides,
})

describe('taxonomicBreakdownFilterLogic', () => {
    let logic: ReturnType<typeof taxonomicBreakdownFilterLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    describe('addBreakdown', () => {
        it('sets breakdown for events', async () => {
            logic = taxonomicBreakdownFilterLogic(makeProps({ breakdownFilter: {} }))
            logic.mount()
            const changedBreakdown = 'c'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdowns: [
                    {
                        property: 'c',
                        type: 'event',
                    },
                ],
            })
        })

        it('sets breakdown for cohorts', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'cohort',
                        breakdown: ['all', 1],
                    },
                })
            )
            logic.mount()
            const changedBreakdown = 2
            const group: TaxonomicFilterGroup = taxonomicGroupFor(
                TaxonomicFilterGroupType.CohortsWithAllUsers,
                undefined
            )

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: 'cohort',
                breakdown: ['all', 1, 2],
                breakdown_group_type_index: undefined,
                breakdown_normalize_url: undefined,
                breakdown_histogram_bin_count: undefined,
            })
        })

        it('sets breakdown for person properties', async () => {
            logic = taxonomicBreakdownFilterLogic(makeProps({ breakdownFilter: {} }))
            logic.mount()
            const changedBreakdown = 'height'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.PersonProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdowns: [
                    {
                        property: 'height',
                        type: 'person',
                    },
                ],
            })
        })

        it('sets breakdown for group properties', async () => {
            logic = taxonomicBreakdownFilterLogic(makeProps({ breakdownFilter: {} }))
            logic.mount()
            const changedBreakdown = '$lib_version'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.GroupsPrefix, 0)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdowns: [
                    {
                        property: '$lib_version',
                        type: 'group',
                        group_type_index: 0,
                    },
                ],
            })
        })

        it('resets the map view when adding a next breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown: '$geoip_country_code',
                        breakdown_type: 'person',
                    },
                    display: ChartDisplayType.WorldMap,
                })
            )
            logic.mount()
            const changedBreakdown = 'c'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdowns: [
                    {
                        property: '$geoip_country_code',
                        type: 'person',
                    },
                    {
                        property: 'c',
                        type: 'event',
                    },
                ],
            })
        })

        it('sets a limit', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'event',
                        breakdown: 'prop',
                    },
                })
            )
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setBreakdownLimit(99)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: 'event',
                breakdown: 'prop',
                breakdown_limit: 99,
            })
        })

        it('sets a hide other aggregation', async () => {
            logic = taxonomicBreakdownFilterLogic(makeProps({ breakdownFilter: {} }))
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setBreakdownHideOtherAggregation(true)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_hide_other_aggregation: true,
            })
        })
    })

    describe('addBreakdownDisabledReason', () => {
        it('no breakdowns', async () => {
            logic = taxonomicBreakdownFilterLogic(makeProps({ breakdownFilter: {} }))
            logic.mount()
            await expectLogic(logic).toMatchValues({
                addBreakdownDisabledReason: null,
            })
        })

        it('multiple breakdowns', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdowns: [],
                    },
                })
            )
            logic.mount()
            await expectLogic(logic).toMatchValues({
                addBreakdownDisabledReason: null,
            })
        })

        it('multiple breakdowns can be added', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdowns: [
                            {
                                property: 'prop1',
                                type: 'event',
                            },
                        ],
                    },
                })
            )
            logic.mount()
            await expectLogic(logic).toMatchValues({
                addBreakdownDisabledReason: null,
            })

            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdowns: [
                            {
                                property: 'prop1',
                                type: 'event',
                            },
                            {
                                property: 'prop2',
                                type: 'event',
                            },
                        ],
                    },
                })
            )
            logic.mount()
            await expectLogic(logic).toMatchValues({
                addBreakdownDisabledReason: null,
            })
        })

        it('multiple breakdowns allows max three elements', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdowns: [
                            {
                                property: 'prop1',
                                type: 'event',
                            },
                            {
                                property: 'prop2',
                                type: 'event',
                            },
                            {
                                property: 'prop3',
                                type: 'event',
                            },
                        ],
                    },
                })
            )
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            await expectLogic(logic).toMatchValues({
                addBreakdownDisabledReason: expect.stringContaining('up to 3'),
            })
        })

        it('only one data warehouse breakdown is allowed', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'data_warehouse_person_property',
                        breakdown: 'prop',
                    },
                })
            )
            logic.mount()
            await expectLogic(logic).toMatchValues({
                addBreakdownDisabledReason: expect.stringContaining('single breakdown'),
            })

            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'data_warehouse',
                        breakdown: 'prop',
                    },
                })
            )
            logic.mount()
            await expectLogic(logic).toMatchValues({
                addBreakdownDisabledReason: expect.stringContaining('single breakdown'),
            })
        })

        it('no restrictions on cohorts', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'cohort',
                        breakdown: [1],
                    },
                })
            )
            logic.mount()
            await expectLogic(logic).toMatchValues({
                addBreakdownDisabledReason: null,
            })

            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'cohort',
                        breakdown: [1, 2],
                    },
                })
            )
            logic.mount()
            await expectLogic(logic).toMatchValues({
                addBreakdownDisabledReason: null,
            })
        })

        it('funnels limit cohort breakdown to one', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'cohort',
                        breakdown: [1],
                    },
                    isTrends: false,
                    isFunnels: true,
                })
            )
            logic.mount()
            await expectLogic(logic).toMatchValues({
                addBreakdownDisabledReason: expect.stringContaining('single cohort breakdown'),
            })
        })

        it('trends allow multiple cohort breakdowns', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'cohort',
                        breakdown: [1, 2, 3],
                    },
                    isTrends: true,
                    isFunnels: false,
                })
            )
            logic.mount()
            await expectLogic(logic).toMatchValues({
                addBreakdownDisabledReason: null,
            })
        })

        it('funnels allow first cohort breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'cohort',
                        breakdown: [],
                    },
                    isTrends: false,
                    isFunnels: true,
                })
            )
            logic.mount()
            await expectLogic(logic).toMatchValues({
                addBreakdownDisabledReason: null,
            })
        })
    })

    describe('multiple breakdowns', () => {
        it('adds a breakdown for events', async () => {
            logic = taxonomicBreakdownFilterLogic(makeProps({ breakdownFilter: {} }))
            logic.mount()

            const changedBreakdown = 'c'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: undefined,
                breakdowns: [
                    {
                        property: 'c',
                        type: 'event',
                    },
                ],
                breakdown_group_type_index: undefined,
                breakdown_histogram_bin_count: undefined,
            })
        })

        it('appends a second distinct breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdowns: [
                            {
                                property: 'c',
                                type: 'event',
                            },
                        ],
                    },
                })
            )
            logic.mount()

            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown('d', group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: undefined,
                breakdowns: [
                    { property: 'c', type: 'event' },
                    { property: 'd', type: 'event' },
                ],
                breakdown_group_type_index: undefined,
                breakdown_histogram_bin_count: undefined,
                breakdown_normalize_url: undefined,
            })
        })

        it('does not add a duplicate breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdowns: [
                            {
                                property: 'c',
                                type: 'event',
                            },
                        ],
                    },
                })
            )
            logic.mount()

            const changedBreakdown = 'c'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).not.toHaveBeenCalled()
        })

        it('adds a breakdown for persons', async () => {
            logic = taxonomicBreakdownFilterLogic(makeProps({ breakdownFilter: {} }))
            logic.mount()
            const changedBreakdown = 'height'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.PersonProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: undefined,
                breakdowns: [
                    {
                        property: 'height',
                        type: 'person',
                    },
                ],
                breakdown_group_type_index: undefined,
                breakdown_histogram_bin_count: undefined,
            })
        })

        it('adds a breakdown for group properties', async () => {
            logic = taxonomicBreakdownFilterLogic(makeProps({ breakdownFilter: {} }))
            logic.mount()
            const changedBreakdown = '$lib_version'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.GroupsPrefix, 0)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: undefined,
                breakdowns: [
                    {
                        type: 'group',
                        property: '$lib_version',
                        group_type_index: 0,
                    },
                ],
                breakdown_group_type_index: undefined,
                breakdown_histogram_bin_count: undefined,
            })
        })

        it('replaces a breakdown correctly', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdowns: [
                            {
                                property: 'c',
                                type: 'event',
                            },
                        ],
                    },
                })
            )
            logic.mount()
            const changedBreakdown = 'c'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.replaceBreakdown(
                    {
                        type: 'event',
                        value: changedBreakdown,
                    },
                    {
                        group: group,
                        value: 'a',
                    }
                )
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: undefined,
                breakdowns: [
                    {
                        type: 'event',
                        property: 'a',
                    },
                ],
                breakdown_group_type_index: undefined,
                breakdown_histogram_bin_count: undefined,
            })
        })

        it('replaceBreakdown does not create a duplicate', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdowns: [
                            {
                                property: 'c',
                                type: 'event',
                            },
                            {
                                property: 'duplicate',
                                type: 'event',
                            },
                        ],
                    },
                })
            )
            logic.mount()
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.replaceBreakdown(
                    {
                        type: 'event',
                        value: 'c',
                    },
                    {
                        group: group,
                        value: 'duplicate',
                    }
                )
            }).toFinishListeners()

            expect(updateBreakdownFilter).not.toHaveBeenCalled()
        })

        it('replaceBreakdown replaces a data warehouse breakdown with multiple breakdowns', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown: 'prop',
                        breakdown_type: 'data_warehouse',
                    },
                })
            )
            logic.mount()
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.replaceBreakdown(
                    {
                        type: 'data_warehouse',
                        value: 'prop',
                    },
                    {
                        group: group,
                        value: 'prop2',
                    }
                )
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdowns: [
                    {
                        type: 'event',
                        property: 'prop2',
                    },
                ],
            })
        })

        it('replaceBreakdown replaces a data warehouse breakdown with a single breakdown on another data warehouse breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown: 'prop',
                        breakdown_type: 'data_warehouse',
                    },
                })
            )
            logic.mount()
            const group: TaxonomicFilterGroup = taxonomicGroupFor(
                TaxonomicFilterGroupType.DataWarehousePersonProperties,
                undefined
            )

            await expectLogic(logic, () => {
                logic.actions.replaceBreakdown(
                    {
                        type: 'data_warehouse',
                        value: 'prop',
                    },
                    {
                        group: group,
                        value: 'prop2',
                    }
                )
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdowns: undefined,
                breakdown_type: 'data_warehouse_person_property',
                breakdown: 'prop2',
            })
        })

        it('replaceBreakdown replaces multiple breakdowns with a single breakdown when there is a data warehouse', async () => {
            const updateBreakdownFilter = jest.fn().mockImplementation()
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdowns: [
                            {
                                type: 'event',
                                property: 'prop',
                            },
                        ],
                    },
                    updateBreakdownFilter,
                })
            )
            logic.mount()
            const group: TaxonomicFilterGroup = taxonomicGroupFor(
                TaxonomicFilterGroupType.DataWarehousePersonProperties,
                undefined
            )

            await expectLogic(logic, () => {
                logic.actions.replaceBreakdown(
                    {
                        type: 'event',
                        value: 'prop',
                    },
                    {
                        group: group,
                        value: 'prop2',
                    }
                )
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdowns: undefined,
                breakdown_type: 'data_warehouse_person_property',
                breakdown: 'prop2',
            })

            expect(updateBreakdownFilter.mock.calls[0][0]).toHaveProperty('breakdowns', undefined)
        })

        it('replaceBreakdown replaces a cohort instead of appending', async () => {
            const updateBreakdownFilter = jest.fn()
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'cohort',
                        breakdown: [1],
                    },
                    isTrends: false,
                    isFunnels: true,
                    updateBreakdownFilter,
                })
            )
            logic.mount()
            const group: TaxonomicFilterGroup = taxonomicGroupFor(
                TaxonomicFilterGroupType.CohortsWithAllUsers,
                undefined
            )

            await expectLogic(logic, () => {
                logic.actions.replaceBreakdown(
                    {
                        type: 'cohort',
                        value: 1,
                    },
                    {
                        group: group,
                        value: 2,
                    }
                )
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown: [2],
                breakdown_type: 'cohort',
            })
        })

        it('resets the map view when adding a next breakdown', async () => {
            const logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdowns: [{ property: '$geoip_country_code', type: 'person' }],
                    },
                    display: ChartDisplayType.WorldMap,
                })
            )
            logic.mount()
            const changedBreakdown = 'c'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdowns: [
                    { property: '$geoip_country_code', type: 'person' },
                    { property: 'c', type: 'event' },
                ],
            })
            expect(updateDisplay).toHaveBeenCalledWith(undefined)
        })
    })

    describe('single breakdown to multiple breakdowns', () => {
        it('addBreakdown: replaces a breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown: 'prop',
                        breakdown_type: 'event',
                        breakdown_normalize_url: true,
                        breakdown_group_type_index: 0,
                        breakdown_histogram_bin_count: 10,
                        breakdown_hide_other_aggregation: true,
                        breakdown_limit: 10,
                    },
                })
            )
            logic.mount()
            const changedBreakdown = 'c'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown: undefined,
                breakdown_type: undefined,
                breakdown_histogram_bin_count: undefined,
                breakdown_normalize_url: undefined,
                breakdowns: [
                    {
                        property: 'prop',
                        type: 'event',
                        normalize_url: true,
                        group_type_index: 0,
                        histogram_bin_count: 10,
                    },
                    {
                        property: 'c',
                        type: 'event',
                    },
                ],
            })
        })

        it('addBreakdown: does not add a duplicate multiple breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown: 'prop',
                        breakdown_type: 'event',
                        breakdown_normalize_url: true,
                        breakdown_group_type_index: 0,
                        breakdown_histogram_bin_count: 10,
                        breakdown_hide_other_aggregation: true,
                        breakdown_limit: 10,
                    },
                })
            )
            logic.mount()
            const changedBreakdown = 'prop'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).not.toHaveBeenCalled()
        })

        it('addBreakdown: does not migrate a cohort breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'cohort',
                        breakdown: ['all', 1],
                    },
                })
            )
            logic.mount()
            const changedBreakdown = 2
            const group: TaxonomicFilterGroup = taxonomicGroupFor(
                TaxonomicFilterGroupType.CohortsWithAllUsers,
                undefined
            )

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: 'cohort',
                breakdown: ['all', 1, 2],
                breakdown_group_type_index: undefined,
                breakdown_normalize_url: undefined,
                breakdown_histogram_bin_count: undefined,
            })
        })

        it('addBreakdown: does not migrate a data warehouse properties breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'data_warehouse',
                        breakdown: 'prop',
                    },
                })
            )
            logic.mount()
            const changedBreakdown = 'new_prop'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(
                TaxonomicFilterGroupType.DataWarehouseProperties,
                undefined
            )

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: 'data_warehouse',
                breakdown: 'new_prop',
            })
        })

        it('addBreakdown: does not migrate a data warehouse person property breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'data_warehouse_person_property',
                        breakdown: 'prop',
                    },
                })
            )
            logic.mount()
            const changedBreakdown = 'new_prop'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(
                TaxonomicFilterGroupType.DataWarehousePersonProperties,
                undefined
            )

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: 'data_warehouse_person_property',
                breakdown: 'new_prop',
            })
        })

        // In the UI it's not possible to add a second breakdown to a data warehouse query, but just in case.
        it('addBreakdown: does add multiple breakdowns when there is a data warehouse breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'data_warehouse_person_property',
                        breakdown: 'prop',
                    },
                })
            )
            logic.mount()
            const changedBreakdown = 'new_prop'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.PersonProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdowns: [
                    {
                        type: 'person',
                        property: 'new_prop',
                    },
                ],
            })
        })

        it('addBreakdown: handles existing cohort breakdown and a new non-cohort property', async () => {
            const updateBreakdownFilter = jest.fn().mockImplementation()

            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'cohort',
                        breakdown: [1, 2],
                    },
                    updateBreakdownFilter,
                })
            )
            logic.mount()
            const changedBreakdown = '$lib_version'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.GroupsPrefix, 0)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: undefined,
                breakdown: undefined,
                breakdowns: [
                    {
                        type: 'group',
                        property: '$lib_version',
                        group_type_index: 0,
                    },
                ],
            })
            expect(updateBreakdownFilter.mock.calls[0][0]).toHaveProperty('breakdown', undefined)
            expect(updateBreakdownFilter.mock.calls[0][0]).toHaveProperty('breakdown_type', undefined)
            expect(updateBreakdownFilter.mock.calls[0][0]).toHaveProperty('breakdown_group_type_index', undefined)
            expect(updateBreakdownFilter.mock.calls[0][0]).toHaveProperty('breakdown_histogram_bin_count', undefined)
            expect(updateBreakdownFilter.mock.calls[0][0]).toHaveProperty('breakdown_normalize_url', undefined)
        })

        it('removeBreakdown: deletes a breakdown correctly', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown_type: 'event',
                        breakdown: 'prop',
                    },
                })
            )
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.removeBreakdown('prop', 'event')
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({})
        })

        it('replaceBreakdown: replaces a breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown: 'prop',
                        breakdown_type: 'event',
                        breakdown_normalize_url: true,
                        breakdown_group_type_index: 0,
                        breakdown_histogram_bin_count: 10,
                        breakdown_hide_other_aggregation: true,
                        breakdown_limit: 10,
                    },
                })
            )
            logic.mount()
            const changedBreakdown = 'c'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.PersonProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.replaceBreakdown(
                    {
                        type: 'event',
                        value: 'prop',
                    },
                    {
                        value: changedBreakdown,
                        group,
                    }
                )
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown: undefined,
                breakdown_type: undefined,
                breakdown_histogram_bin_count: undefined,
                breakdown_normalize_url: undefined,
                breakdown_group_type_index: undefined,
                breakdowns: [
                    {
                        property: 'c',
                        type: 'person',
                    },
                ],
            })
        })

        it('replaceBreakdown: does not add a duplicate multiple breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown: 'prop',
                        breakdown_type: 'event',
                        breakdown_normalize_url: true,
                        breakdown_group_type_index: 0,
                        breakdown_histogram_bin_count: 10,
                        breakdown_hide_other_aggregation: true,
                        breakdown_limit: 10,
                    },
                })
            )
            logic.mount()
            const changedBreakdown = 'prop'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.replaceBreakdown(
                    {
                        type: 'event',
                        value: 'prop',
                    },
                    {
                        value: changedBreakdown,
                        group,
                    }
                )
            }).toFinishListeners()

            expect(updateBreakdownFilter).not.toHaveBeenCalled()
        })

        it('setNormalizeBreakdownURL: updates correctly', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown: 'prop',
                        breakdown_type: 'event',
                        breakdown_normalize_url: true,
                    },
                })
            )
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setNormalizeBreakdownURL('prop', 'event', false)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({ breakdown_normalize_url: false })
        })

        it('setHistogramBinsUsed: updates correctly', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown: 'prop',
                        breakdown_type: 'event',
                        breakdown_histogram_bin_count: 10,
                    },
                })
            )
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setHistogramBinsUsed('prop', 'event', false)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({ breakdown_histogram_bin_count: undefined })
        })

        it('setHistogramBinCount: updates correctly', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown: 'prop',
                        breakdown_type: 'event',
                        breakdown_histogram_bin_count: 5,
                    },
                })
            )
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setHistogramBinCount('prop', 'event', 10)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({ breakdown_histogram_bin_count: 10 })
        })

        it('setBreakdownLimit: updates correctly', async () => {
            logic = taxonomicBreakdownFilterLogic(
                makeProps({
                    breakdownFilter: {
                        breakdown: 'prop',
                        breakdown_type: 'event',
                        breakdown_limit: 10,
                    },
                })
            )
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setBreakdownLimit(99)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown: 'prop',
                breakdown_type: 'event',
                breakdown_limit: 99,
            })
        })

        it('setBreakdownHideOtherAggregation: updates correctly', async () => {
            logic = taxonomicBreakdownFilterLogic(makeProps({ breakdownFilter: {} }))
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setBreakdownHideOtherAggregation(true)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_hide_other_aggregation: true,
            })
        })
    })
})
