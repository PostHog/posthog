import { expectLogic } from 'kea-test-utils'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { initKeaTests } from '~/test/init'
import { InsightLogicProps } from '~/types'

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

function mockFeatureFlag(logic: any): void {
    logic.selectors.isMultipleBreakdownsEnabled = jest.fn().mockReturnValue(true)
}

describe('taxonomicBreakdownFilterLogic', () => {
    let logic: ReturnType<typeof taxonomicBreakdownFilterLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    describe('addBreakdown', () => {
        it('sets breakdown for events', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {},
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()
            const changedBreakdown = 'c'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: 'event',
                breakdown: 'c',
                breakdown_group_type_index: undefined,
                breakdown_histogram_bin_count: undefined,
            })
        })

        it('sets breakdown for cohorts', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown_type: 'cohort',
                    breakdown: ['all', 1],
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
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
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {},
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()
            const changedBreakdown = 'height'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.PersonProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: 'person',
                breakdown: 'height',
                breakdown_group_type_index: undefined,
            })
        })

        it('sets breakdown for group properties', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {},
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()
            const changedBreakdown = '$lib_version'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.GroupsPrefix, 0)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_type: 'group',
                breakdown: '$lib_version',
                breakdown_group_type_index: 0,
            })
        })

        it('sets a limit', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {},
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setBreakdownLimit(99)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_limit: 99,
            })
        })

        it('sets a hide other aggregation', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {},
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setBreakdownHideOtherAggregation(true)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_hide_other_aggregation: true,
            })
        })
    })

    describe('isAddBreakdownDisabled', () => {
        function mockFeatureFlag(): void {
            jest.spyOn(breakdownLogic, 'multipleBreakdownsEnabled').mockReturnValue(true)
        }

        it('no breakdowns', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {},
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                isAddBreakdownDisabled: false,
            })
        })

        it('breakdown is selected', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown: 'prop',
                    breakdown_type: 'event',
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                isAddBreakdownDisabled: true,
            })
        })

        it('multiple breakdowns', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdowns: [],
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                isAddBreakdownDisabled: false,
            })
        })

        it('multiple breakdowns can be added', async () => {
            mockFeatureFlag()

            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdowns: [
                        {
                            value: 'prop1',
                            type: 'event',
                        },
                    ],
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                isAddBreakdownDisabled: false,
            })

            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdowns: [
                        {
                            value: 'prop1',
                            type: 'event',
                        },
                        {
                            value: 'prop2',
                            type: 'event',
                        },
                    ],
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                isAddBreakdownDisabled: false,
            })
        })

        it('multiple breakdowns allows max three elements', async () => {
            mockFeatureFlag()
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdowns: [
                        {
                            value: 'prop1',
                            type: 'event',
                        },
                        {
                            value: 'prop2',
                            type: 'event',
                        },
                        {
                            value: 'prop3',
                            type: 'event',
                        },
                    ],
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            await expectLogic(logic).toMatchValues({
                isAddBreakdownDisabled: true,
            })
        })

        it('only one data warehouse breakdown is allowed', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown_type: 'data_warehouse_person_property',
                    breakdown: 'prop',
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                isAddBreakdownDisabled: true,
            })

            mockFeatureFlag()

            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown_type: 'data_warehouse',
                    breakdown: 'prop',
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                isAddBreakdownDisabled: true,
            })
        })

        it('no restrictions on cohorts', async () => {
            mockFeatureFlag()
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown_type: 'cohort',
                    breakdown: [1],
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                isAddBreakdownDisabled: false,
            })

            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown_type: 'cohort',
                    breakdown: [1, 2],
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                isAddBreakdownDisabled: false,
            })
        })
    })

    describe('multiple breakdowns', () => {
        it('adds a breakdown for events', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {},
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
                        value: 'c',
                        type: 'event',
                    },
                ],
                breakdown_group_type_index: undefined,
                breakdown_histogram_bin_count: undefined,
            })
        })

        it('does not add a duplicate breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdowns: [
                        {
                            value: 'c',
                            type: 'event',
                        },
                    ],
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
            logic.mount()

            const changedBreakdown = 'c'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).not.toHaveBeenCalled()
        })

        it('adds a breakdown for persons', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {},
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
                        value: 'height',
                        type: 'person',
                    },
                ],
                breakdown_group_type_index: undefined,
                breakdown_histogram_bin_count: undefined,
            })
        })

        it('adds a breakdown for group properties', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {},
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
                        value: '$lib_version',
                        group_type_index: 0,
                    },
                ],
                breakdown_group_type_index: undefined,
                breakdown_histogram_bin_count: undefined,
            })
        })

        it('replaces a breakdown correctly', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdowns: [
                        {
                            value: 'c',
                            type: 'event',
                        },
                    ],
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
                        value: 'a',
                    },
                ],
                breakdown_group_type_index: undefined,
                breakdown_histogram_bin_count: undefined,
            })
        })

        it('replaceBreakdown does not create a duplicate', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdowns: [
                        {
                            value: 'c',
                            type: 'event',
                        },
                        {
                            value: 'duplicate',
                            type: 'event',
                        },
                    ],
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
                        value: 'duplicate',
                    }
                )
            }).toFinishListeners()

            expect(updateBreakdownFilter).not.toHaveBeenCalled()
        })

        it('replaceBreakdown replaces a data warehouse breakdown with multiple breakdowns', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown: 'prop',
                    breakdown_type: 'data_warehouse',
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
                        value: 'prop2',
                    },
                ],
            })
        })

        it('replaceBreakdown replaces a data warehouse breakdown with a single breakdown on another data warehouse breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown: 'prop',
                    breakdown_type: 'data_warehouse',
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdowns: [
                        {
                            type: 'event',
                            value: 'prop',
                        },
                    ],
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
    })

    describe('single breakdown to multiple breakdowns', () => {
        it('addBreakdown: replaces a breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown: 'prop',
                    breakdown_type: 'event',
                    breakdown_normalize_url: true,
                    breakdown_group_type_index: 0,
                    breakdown_histogram_bin_count: 10,
                    breakdown_hide_other_aggregation: true,
                    breakdown_limit: 10,
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
                        value: 'prop',
                        type: 'event',
                        normalize_url: true,
                        group_type_index: 0,
                        histogram_bin_count: 10,
                    },
                    {
                        value: 'c',
                        type: 'event',
                    },
                ],
            })
        })

        it('addBreakdown: does not add a duplicate multiple breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown: 'prop',
                    breakdown_type: 'event',
                    breakdown_normalize_url: true,
                    breakdown_group_type_index: 0,
                    breakdown_histogram_bin_count: 10,
                    breakdown_hide_other_aggregation: true,
                    breakdown_limit: 10,
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
            logic.mount()
            const changedBreakdown = 'prop'
            const group: TaxonomicFilterGroup = taxonomicGroupFor(TaxonomicFilterGroupType.EventProperties, undefined)

            await expectLogic(logic, () => {
                logic.actions.addBreakdown(changedBreakdown, group)
            }).toFinishListeners()

            expect(updateBreakdownFilter).not.toHaveBeenCalled()
        })

        it('addBreakdown: does not migrate a cohort breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown_type: 'cohort',
                    breakdown: ['all', 1],
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown_type: 'data_warehouse',
                    breakdown: 'prop',
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown_type: 'data_warehouse_person_property',
                    breakdown: 'prop',
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown_type: 'data_warehouse_person_property',
                    breakdown: 'prop',
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
                        value: 'new_prop',
                    },
                ],
            })
        })

        it('addBreakdown: handles existing cohort breakdown and a new non-cohort property', async () => {
            const updateBreakdownFilter = jest.fn().mockImplementation()

            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown_type: 'cohort',
                    breakdown: [1, 2],
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
                        value: '$lib_version',
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
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown_type: 'event',
                    breakdown: 'prop',
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.removeBreakdown('prop', 'event')
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({})
        })

        it('replaceBreakdown: replaces a breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown: 'prop',
                    breakdown_type: 'event',
                    breakdown_normalize_url: true,
                    breakdown_group_type_index: 0,
                    breakdown_histogram_bin_count: 10,
                    breakdown_hide_other_aggregation: true,
                    breakdown_limit: 10,
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
                        value: 'c',
                        type: 'person',
                    },
                ],
            })
        })

        it('replaceBreakdown: does not add a duplicate multiple breakdown', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown: 'prop',
                    breakdown_type: 'event',
                    breakdown_normalize_url: true,
                    breakdown_group_type_index: 0,
                    breakdown_histogram_bin_count: 10,
                    breakdown_hide_other_aggregation: true,
                    breakdown_limit: 10,
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
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
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown: 'prop',
                    breakdown_type: 'event',
                    breakdown_normalize_url: true,
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setNormalizeBreakdownURL('prop', 'event', false)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({ breakdown_normalize_url: false })
        })

        it('setHistogramBinsUsed: updates correctly', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown: 'prop',
                    breakdown_type: 'event',
                    breakdown_histogram_bin_count: 10,
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setHistogramBinsUsed('prop', 'event', false)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({ breakdown_histogram_bin_count: undefined })
        })

        it('setHistogramBinCount: updates correctly', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown: 'prop',
                    breakdown_type: 'event',
                    breakdown_histogram_bin_count: 5,
                },
                histogramBinsUsed: true,
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            mockFeatureFlag(logic)
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setHistogramBinCount('prop', 'event', 10)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({ breakdown_histogram_bin_count: 10 })
        })

        it('setBreakdownLimit: updates correctly', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {
                    breakdown_limit: 10,
                },
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setBreakdownLimit(99)
            }).toFinishListeners()

            expect(updateBreakdownFilter).toHaveBeenCalledWith({
                breakdown_limit: 99,
            })
        })

        it('setBreakdownHideOtherAggregation: updates correctly', async () => {
            logic = taxonomicBreakdownFilterLogic({
                insightProps,
                breakdownFilter: {},
                isTrends: true,
                updateBreakdownFilter,
                updateDisplay,
            })
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
