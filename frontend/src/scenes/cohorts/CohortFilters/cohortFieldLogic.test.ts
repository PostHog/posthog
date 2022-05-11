import { cohortFieldLogic, CohortFieldLogicProps } from 'scenes/cohorts/CohortFilters/cohortFieldLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { groupsModel } from '~/models/groupsModel'
import { MOCK_GROUP_TYPES } from 'lib/api.mock'
import { FieldOptionsType } from 'scenes/cohorts/CohortFilters/types'
import { FIELD_VALUES } from 'scenes/cohorts/CohortFilters/constants'

describe('cohortFieldLogic', () => {
    let logic: ReturnType<typeof cohortFieldLogic.build>
    const filter_groups = FIELD_VALUES

    beforeEach(async () => {
        useMocks({
            get: {
                'api/projects/:team/groups_types': MOCK_GROUP_TYPES,
            },
        })
        initKeaTests()
    })

    async function initLogic(
        props: CohortFieldLogicProps = {
            cohortFilterLogicKey: '0',
            fieldKey: 'value',
            criteria: {},
            fieldOptionGroupTypes: [FieldOptionsType.EventAggregation, FieldOptionsType.PropertyAggregation],
        }
    ): Promise<void> {
        groupsModel.mount()
        await expectLogic(groupsModel).toFinishAllListeners()
        logic = cohortFieldLogic(props)
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
                    fieldKey: 'value',
                    criteria: {},
                    fieldOptionGroupTypes: [key as FieldOptionsType],
                })
                await expectLogic(logic).toMatchValues({
                    fieldOptionGroups: [value],
                })
            })
        }
    })
})
