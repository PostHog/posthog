import { definitionPopupLogic, DefinitionPopupState } from 'lib/components/DefinitionPopup/definitionPopupLogic'
import api from 'lib/api'
import {
    mockActionDefinition,
    mockCohort,
    mockElement,
    mockEventDefinitions,
    mockEventPropertyDefinition,
    mockGroup,
    mockPersonProperty,
} from '~/test/mocks'
import { initKeaTests } from '~/test/init'
import { TaxonomicDefinitionTypes, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { expectLogic } from 'kea-test-utils'
import { urls } from 'scenes/urls'
import { actionsModel } from '~/models/actionsModel'
import { ActionType, CohortType, PersonProperty, PropertyDefinition } from '~/types'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { useMocks } from '~/mocks/jest'

describe('definitionPopupLogic', () => {
    let logic: ReturnType<typeof definitionPopupLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/@current/event_definitions/': {
                    results: mockEventDefinitions,
                    count: mockEventDefinitions.length,
                },
                '/api/projects/@current/property_definitions/': {
                    results: [mockEventPropertyDefinition],
                    count: 1,
                },
                '/api/projects/@current/actions/': {
                    results: [mockActionDefinition],
                    count: 1,
                },
                '/api/projects/@current/cohorts/': {
                    results: [mockCohort],
                    count: 1,
                },
            },
            patch: {
                '/api/projects/@current/:object/:id/': {},
            },
        })

        jest.spyOn(api, 'update')

        initKeaTests()
        actionsModel.mount()
        eventDefinitionsModel.mount()
        propertyDefinitionsModel.mount()
        cohortsModel.mount()
    })

    describe('editing mode', () => {
        beforeEach(() => {
            logic = definitionPopupLogic({
                type: TaxonomicFilterGroupType.Events,
            })
            logic.mount()
        })

        it('make local state dirty', async () => {
            await expectLogic(logic, async () => {
                await logic.actions.setDefinition(mockEventDefinitions[0])
                await logic.actions.setPopupState(DefinitionPopupState.Edit)
            })
                .toDispatchActions(['setDefinition', 'setPopupState'])
                .toMatchValues({
                    state: DefinitionPopupState.Edit,
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
                await logic.actions.setDefinition(mockEventDefinitions[0])
                await logic.actions.setPopupState(DefinitionPopupState.Edit)
                await logic.actions.setLocalDefinition({ description: 'new description' })
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
                    logic.actionCreators.setPopupState(DefinitionPopupState.View),
                    logic.actionCreators.setLocalDefinition(mockEventDefinitions[0]),
                ])
                .toMatchValues({
                    state: DefinitionPopupState.View,
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
                    url: `api/projects/@current/actions/${mockActionDefinition.id}`,
                    dispatchActions: [actionsModel, ['updateAction']],
                },
                {
                    type: TaxonomicFilterGroupType.CustomEvents,
                    definition: mockEventDefinitions[0],
                    url: `api/projects/@current/event_definitions/${mockEventDefinitions[0].id}`,
                    dispatchActions: [eventDefinitionsModel, ['updateEventDefinition']],
                },
                {
                    type: TaxonomicFilterGroupType.Events,
                    definition: mockEventDefinitions[1],
                    url: `api/projects/@current/event_definitions/${mockEventDefinitions[1].id}`,
                    dispatchActions: [eventDefinitionsModel, ['updateEventDefinition']],
                },
                {
                    type: TaxonomicFilterGroupType.PersonProperties,
                    definition: mockPersonProperty as PersonProperty,
                    dispatchActions: [],
                },
                {
                    type: TaxonomicFilterGroupType.EventProperties,
                    definition: mockEventPropertyDefinition as PropertyDefinition,
                    url: `api/projects/@current/property_definitions/${mockEventPropertyDefinition.id}`,
                    dispatchActions: [propertyDefinitionsModel, ['updatePropertyDefinition']],
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
                    definition: mockCohort as CohortType,
                    url: `api/projects/@current/cohorts/${mockCohort.id}`,
                    dispatchActions: [cohortsModel, ['updateCohort']],
                },
                {
                    type: TaxonomicFilterGroupType.Elements,
                    definition: mockElement as TaxonomicDefinitionTypes,
                    dispatchActions: [],
                },
            ]

            groups.forEach((group) => {
                it(group.type, async () => {
                    logic = definitionPopupLogic({
                        type: group.type,
                    })
                    logic.mount()

                    const expectChain = expectLogic(logic, async () => {
                        await logic.actions.setDefinition(group.definition)
                        await logic.actions.setPopupState(DefinitionPopupState.Edit)
                        await logic.actions.setLocalDefinition({ description: 'new and improved description' })
                        await logic.actions.handleSave({})
                    }).toDispatchActions(['setDefinitionSuccess', 'setPopupState', 'handleSave'])

                    if (group.dispatchActions.length > 0) {
                        expectChain.toDispatchActions(group.dispatchActions[0], group.dispatchActions[1])
                    }

                    await expectChain

                    if (group.url) {
                        expect(api.update).toBeCalledWith(
                            group.url,
                            expect.objectContaining({ description: 'new and improved description' })
                        )
                    }
                })
            })
        })

        it('add tags', async () => {
            await expectLogic(logic, async () => {
                await logic.actions.setDefinition(mockEventDefinitions[0])
                await logic.actions.setPopupState(DefinitionPopupState.Edit)
                await logic.actions.setLocalDefinition({ tags: ['ohhello', 'ohwow'] })
            })
                .toDispatchActions(['setDefinitionSuccess', 'setLocalDefinition'])
                .toMatchValues({
                    localDefinition: { ...mockEventDefinitions[0], tags: ['ohhello', 'ohwow'] },
                })
        })
    })

    describe('view mode', () => {
        it('change context', async () => {
            logic = definitionPopupLogic({
                type: TaxonomicFilterGroupType.Events,
            })
            logic.mount()

            await expectLogic(logic, async () => {
                await logic.actions.setDefinition(mockEventDefinitions[0])
                await logic.actions.setDefinition(mockEventDefinitions[1])
            })
                .toDispatchActions(['setDefinitionSuccess'])
                .toMatchValues({
                    definition: mockEventDefinitions[0],
                })
                .toDispatchActions([
                    'setDefinitionSuccess',
                    logic.actionCreators.setPopupState(DefinitionPopupState.View),
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
                    url: urls.eventPropertyDefinition(mockDefinitionId),
                },
                {
                    type: TaxonomicFilterGroupType.EventProperties,
                    url: urls.eventPropertyDefinition(mockDefinitionId),
                },
                {
                    type: TaxonomicFilterGroupType.NumericalEventProperties,
                    url: urls.eventPropertyDefinition(mockDefinitionId),
                },
                {
                    type: `${TaxonomicFilterGroupType.GroupsPrefix}_0`,
                    url: urls.eventPropertyDefinition(mockDefinitionId),
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
                it(group.type, async () => {
                    logic = definitionPopupLogic({
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
