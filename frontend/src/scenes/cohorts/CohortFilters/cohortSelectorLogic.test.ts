import { cohortSelectorLogic, CohortSelectorLogicProps } from 'scenes/cohorts/CohortFilters/cohortSelectorLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { groupsModel } from '~/models/groupsModel'
import { MOCK_GROUP_TYPES } from 'lib/api.mock'
import { FilterGroupTypes } from 'scenes/cohorts/CohortFilters/types'
import { FILTER_GROUPS } from 'scenes/cohorts/CohortFilters/constants'

describe('cohortSelectorLogic', () => {
    let logic: ReturnType<typeof cohortSelectorLogic.build>
    const filter_groups = FILTER_GROUPS

    beforeEach(async () => {
        useMocks({
            get: {
                'api/projects/:team/groups_types': MOCK_GROUP_TYPES,
            },
        })
        initKeaTests()
    })

    async function initLogic(
        props: CohortSelectorLogicProps = {
            cohortFilterLogicKey: '0',
            value: null,
            groupTypes: [FilterGroupTypes.EventAggregation, FilterGroupTypes.PropertyAggregation],
        }
    ): Promise<void> {
        groupsModel.mount()
        await expectLogic(groupsModel).toFinishAllListeners()
        logic = cohortSelectorLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('fetches group types from server on mount', async () => {
        await initLogic()
        await expectLogic(logic).toMount([groupsModel])
        await expectLogic(groupsModel).toDispatchActions(['loadAllGroupTypesSuccess'])
    })

    describe('selects correct group options', () => {
        for (const [key, value] of Object.entries(filter_groups)) {
            it(key, async () => {
                await initLogic({
                    cohortFilterLogicKey: '0',
                    value: null,
                    groupTypes: [key as FilterGroupTypes],
                })
                await expectLogic(logic).toMatchValues({
                    groups: [value],
                })
            })
        }
    })
})
