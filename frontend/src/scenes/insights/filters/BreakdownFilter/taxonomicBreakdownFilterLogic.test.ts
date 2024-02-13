import { expectLogic } from 'kea-test-utils'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { initKeaTests } from '~/test/init'
import { InsightLogicProps } from '~/types'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

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
    })
})
