import { MOCK_GROUP_TYPES } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { CohortFieldLogicProps, cohortFieldLogic } from 'scenes/cohorts/CohortFilters/cohortFieldLogic'
import { FIELD_VALUES } from 'scenes/cohorts/CohortFilters/constants'
import { FieldOptionsType } from 'scenes/cohorts/CohortFilters/types'

import { useMocks } from '~/mocks/jest'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'

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
            it(`select using ${key}`, async () => {
                await initLogic({
                    cohortFilterLogicKey: '0',
                    fieldKey: 'value',
                    criteria: {},
                    fieldOptionGroupTypes: [key as FieldOptionsType],
                })
                await expectLogic(logic).toMatchValues({
                    fieldOptionGroups: [
                        key !== FieldOptionsType.Actors
                            ? value
                            : // Actors also include the group types fetched from the API (here they're MOCK_GROUP_TYPES)
                              {
                                  ...value,
                                  values: {
                                      ...value.values,
                                      group_0: {
                                          label: 'organizations',
                                      },
                                      group_1: {
                                          label: 'instances',
                                      },
                                      group_2: {
                                          label: 'projects',
                                      },
                                  },
                              },
                    ],
                })
            })
        }
    })
})
