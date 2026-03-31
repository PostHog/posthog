import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { DefinitionPopoverState, definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { TaxonomicDefinitionTypes, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import {
    mockActionDefinition,
    mockCohort,
    mockElement,
    mockEventDefinitions,
    mockEventPropertyDefinition,
    mockGroup,
    mockPersonProperty,
} from '~/test/mocks'
import { ActionType, CohortType, PersonProperty, PropertyDefinition } from '~/types'

describe('definitionPopoverLogic', () => {
    let logic: ReturnType<typeof definitionPopoverLogic.build>
    const mockDataWarehouseTable: DataWarehouseTableForInsight = {
        id: 'warehouse-table-id',
        name: 'warehouse_table',
        type: 'data_warehouse',
        format: 'Parquet',
        url_pattern: '',
        fields: {
            id: { name: 'id', hogql_value: 'id', type: 'integer', schema_valid: true },
            distinct_id: { name: 'distinct_id', hogql_value: 'distinct_id', type: 'string', schema_valid: true },
            created_at: { name: 'created_at', hogql_value: 'created_at', type: 'datetime', schema_valid: true },
            user_uuid: { name: 'user_uuid', hogql_value: 'user_uuid', type: 'string', schema_valid: true },
            event_timestamp: {
                name: 'event_timestamp',
                hogql_value: 'event_timestamp',
                type: 'datetime',
                schema_valid: true,
            },
            row_uuid: { name: 'row_uuid', hogql_value: 'row_uuid', type: 'string', schema_valid: true },
        },
    }

    beforeEach(() => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/event_definitions/`]: {
                    results: mockEventDefinitions,
                    count: mockEventDefinitions.length,
                },
                [`/api/projects/${MOCK_TEAM_ID}/property_definitions/`]: {
                    results: [mockEventPropertyDefinition],
                    count: 1,
                },
                [`/api/projects/${MOCK_TEAM_ID}/actions/`]: {
                    results: [mockActionDefinition],
                    count: 1,
                },
                [`/api/projects/${MOCK_TEAM_ID}/cohorts/`]: {
                    results: [mockCohort],
                    count: 1,
                },
            },
            patch: {
                [`/api/projects/${MOCK_TEAM_ID}/:object/:id/`]: {},
            },
        })

        jest.spyOn(api, 'update')

        initKeaTests()
        actionsModel.mount()
        propertyDefinitionsModel.mount()
        cohortsModel.mount()
    })

    describe('editing mode', () => {
        beforeEach(() => {
            logic = definitionPopoverLogic({
                type: TaxonomicFilterGroupType.Events,
            })
            logic.mount()
        })

        it('make local state dirty', async () => {
            await expectLogic(logic, async () => {
                logic.actions.setDefinition(mockEventDefinitions[0])
                logic.actions.setPopoverState(DefinitionPopoverState.Edit)
            })
                .toDispatchActions(['setDefinition', 'setPopoverState'])
                .toMatchValues({
                    state: DefinitionPopoverState.Edit,
                    dirty: false,
                    definition: mockEventDefinitions[0],
                    localDefinition: mockEventDefinitions[0],
                })
            await expectLogic(logic, () => {
                logic.actions.setLocalDefinition({ description: 'new description' })
            })
                .toDispatchActions(['setLocalDefinition'])
                .toMatchValues({
                    dirty: true,
                    localDefinition: { ...mockEventDefinitions[0], description: 'new description' },
                })
        })

        it('cancel', async () => {
            await expectLogic(logic, async () => {
                logic.actions.setDefinition(mockEventDefinitions[0])
                logic.actions.setPopoverState(DefinitionPopoverState.Edit)
                logic.actions.setLocalDefinition({ description: 'new description' })
            })
                .toDispatchActions(['setLocalDefinition'])
                .toMatchValues({
                    dirty: true,
                })

            await expectLogic(logic, () => {
                logic.actions.handleCancel()
            })
                .toDispatchActions([
                    'handleCancel',
                    logic.actionCreators.setPopoverState(DefinitionPopoverState.View),
                    logic.actionCreators.setLocalDefinition(mockEventDefinitions[0]),
                ])
                .toMatchValues({
                    state: DefinitionPopoverState.View,
                    dirty: false,
                    localDefinition: mockEventDefinitions[0],
                })
        })

        describe('save', () => {
            const groups: {
                type: TaxonomicFilterGroupType | string
                definition: TaxonomicDefinitionTypes
                url?: string
                dispatchActions: any[]
            }[] = [
                {
                    type: TaxonomicFilterGroupType.Actions,
                    definition: mockActionDefinition as ActionType,
                    url: `api/projects/${MOCK_TEAM_ID}/actions/${mockActionDefinition.id}`,
                    dispatchActions: [actionsModel, ['updateAction']],
                },
                {
                    type: TaxonomicFilterGroupType.CustomEvents,
                    definition: mockEventDefinitions[0],
                    url: `api/projects/${MOCK_TEAM_ID}/event_definitions/${mockEventDefinitions[0].id}`,
                    dispatchActions: [],
                },
                {
                    type: TaxonomicFilterGroupType.Events,
                    definition: mockEventDefinitions[1],
                    url: `api/projects/${MOCK_TEAM_ID}/event_definitions/${mockEventDefinitions[1].id}`,
                    dispatchActions: [],
                },
                {
                    type: TaxonomicFilterGroupType.PersonProperties,
                    definition: mockPersonProperty as PersonProperty,
                    dispatchActions: [],
                },
                {
                    type: TaxonomicFilterGroupType.EventProperties,
                    definition: mockEventPropertyDefinition as PropertyDefinition,
                    url: `api/projects/${MOCK_TEAM_ID}/property_definitions/${mockEventPropertyDefinition.id}`,
                    dispatchActions: [propertyDefinitionsModel, ['updatePropertyDefinitions']],
                },
                {
                    type: TaxonomicFilterGroupType.NumericalEventProperties,
                    definition: mockEventPropertyDefinition as PropertyDefinition,
                    dispatchActions: [],
                },
                {
                    type: `${TaxonomicFilterGroupType.GroupsPrefix}_0`,
                    definition: mockGroup as CohortType,
                    dispatchActions: [],
                },
                {
                    type: TaxonomicFilterGroupType.Cohorts,
                    definition: mockCohort,
                    url: `api/projects/${MOCK_TEAM_ID}/cohorts/${mockCohort.id}`,
                    dispatchActions: [cohortsModel, ['updateCohort']],
                },
                {
                    type: TaxonomicFilterGroupType.Elements,
                    definition: mockElement as TaxonomicDefinitionTypes,
                    dispatchActions: [],
                },
            ]

            groups.forEach((group) => {
                it(`with ${group.type}`, async () => {
                    logic = definitionPopoverLogic({
                        type: group.type,
                    })
                    logic.mount()

                    const expectChain = expectLogic(logic, async () => {
                        logic.actions.setDefinition(group.definition)
                        logic.actions.setPopoverState(DefinitionPopoverState.Edit)
                        logic.actions.setLocalDefinition({ description: 'new and improved description' })
                        logic.actions.handleSave({})
                    }).toDispatchActions(['setDefinitionSuccess', 'setPopoverState', 'handleSave'])

                    if (group.dispatchActions.length > 0) {
                        expectChain.toDispatchActions(group.dispatchActions[0], group.dispatchActions[1])
                    }

                    await expectChain

                    if (group.url) {
                        expect(api.update).toHaveBeenCalledWith(
                            group.url,
                            expect.objectContaining({ description: 'new and improved description' })
                        )
                    }
                })
            })
        })

        it('add tags', async () => {
            await expectLogic(logic, async () => {
                logic.actions.setDefinition(mockEventDefinitions[0])
                logic.actions.setPopoverState(DefinitionPopoverState.Edit)
                logic.actions.setLocalDefinition({ tags: ['ohhello', 'ohwow'] })
            })
                .toDispatchActions(['setDefinitionSuccess', 'setLocalDefinition'])
                .toMatchValues({
                    localDefinition: { ...mockEventDefinitions[0], tags: ['ohhello', 'ohwow'] },
                })
        })
    })

    describe('view mode', () => {
        it('hydrates data warehouse fields from the selected filter before applying defaults', async () => {
            logic = definitionPopoverLogic({
                type: TaxonomicFilterGroupType.DataWarehouse,
                selectedItemMeta: {
                    id: 'warehouse_table',
                    table_name: 'warehouse_table',
                    distinct_id_field: 'user_uuid',
                    timestamp_field: 'event_timestamp',
                    id_field: 'row_uuid',
                },
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setDefinition(mockDataWarehouseTable)
            })
                .toDispatchActions(['setDefinitionSuccess'])
                .toMatchValues({
                    localDefinition: expect.objectContaining({
                        distinct_id_field: 'user_uuid',
                        timestamp_field: 'event_timestamp',
                        id_field: 'row_uuid',
                    }),
                })
        })

        it('change context', async () => {
            logic = definitionPopoverLogic({
                type: TaxonomicFilterGroupType.Events,
            })
            logic.mount()

            await expectLogic(logic, async () => {
                logic.actions.setDefinition(mockEventDefinitions[0])
                logic.actions.setDefinition(mockEventDefinitions[1])
            })
                .toDispatchActions(['setDefinitionSuccess'])
                .toMatchValues({
                    definition: mockEventDefinitions[0],
                })
                .toDispatchActions([
                    'setDefinitionSuccess',
                    logic.actionCreators.setPopoverState(DefinitionPopoverState.View),
                ])
                .toMatchValues({
                    definition: mockEventDefinitions[1],
                })
        })

        describe('redirect to full detail', () => {
            const mockDefinitionId = 'mock-definition-id'
            const groups: { type: TaxonomicFilterGroupType | string; url: string | null }[] = [
                {
                    type: TaxonomicFilterGroupType.Actions,
                    url: urls.action(mockDefinitionId),
                },
                {
                    type: TaxonomicFilterGroupType.CustomEvents,
                    url: urls.eventDefinition(mockDefinitionId),
                },
                {
                    type: TaxonomicFilterGroupType.Events,
                    url: urls.eventDefinition(mockDefinitionId),
                },
                {
                    type: TaxonomicFilterGroupType.PersonProperties,
                    url: urls.propertyDefinition(mockDefinitionId),
                },
                {
                    type: TaxonomicFilterGroupType.EventProperties,
                    url: urls.propertyDefinition(mockDefinitionId),
                },
                {
                    type: TaxonomicFilterGroupType.NumericalEventProperties,
                    url: urls.propertyDefinition(mockDefinitionId),
                },
                {
                    type: `${TaxonomicFilterGroupType.GroupsPrefix}_0`,
                    url: urls.propertyDefinition(mockDefinitionId),
                },
                {
                    type: TaxonomicFilterGroupType.Cohorts,
                    url: urls.cohort(mockDefinitionId),
                },
                {
                    type: TaxonomicFilterGroupType.Elements,
                    url: null,
                },
            ]

            groups.forEach((group) => {
                it(`with ${group.type}`, async () => {
                    logic = definitionPopoverLogic({
                        type: group.type,
                    })
                    logic.mount()

                    const expectChain = expectLogic(logic, () => {
                        logic.actions.setDefinition({ id: mockDefinitionId })
                    }).toDispatchActions(['setDefinitionSuccess'])

                    if (group.url) {
                        expectChain.toMatchValues({
                            viewFullDetailUrl: group.url,
                        })
                    } else {
                        expectChain.toMatchValues({
                            viewFullDetailUrl: undefined,
                        })
                    }
                    await expectChain
                })
            })
        })
    })
})
