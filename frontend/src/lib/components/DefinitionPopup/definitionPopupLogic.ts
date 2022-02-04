import { kea } from 'kea'
import { router } from 'kea-router'
import { definitionPopupLogicType } from './definitionPopupLogicType'
import { TaxonomicDefinitionTypes, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { capitalizeFirstLetter, errorToast } from 'lib/utils'
import { getSingularType } from 'lib/components/DefinitionPopup/utils'
import { ActionType, CohortType, EventDefinition, PropertyDefinition } from '~/types'
import { urls } from 'scenes/urls'
import api from 'lib/api'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { actionsModel } from '~/models/actionsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { toast } from 'react-toastify'

export enum DefinitionPopupState {
    Edit = 'edit',
    View = 'view',
}

interface DefinitionPopupLogicProps {
    type: TaxonomicFilterGroupType
    item: TaxonomicDefinitionTypes // Clean definition loaded from server
    hasTaxonomyFeatures?: boolean
}

export const definitionPopupLogic = kea<definitionPopupLogicType<DefinitionPopupLogicProps, DefinitionPopupState>>({
    props: {} as DefinitionPopupLogicProps,
    path: ['lib', 'components', 'DefinitionPanel', 'definitionPopupLogic'],
    actions: {
        setDefinition: (item: Partial<TaxonomicDefinitionTypes>) => ({ item }),
        saveDefinition: true,
        setPopupState: (state: DefinitionPopupState) => ({ state }),
        setNewTag: (tag: string) => ({ tag }),
        deleteTag: (tag: string) => ({ tag }),
        handleView: true,
    },
    reducers: {
        state: [
            DefinitionPopupState.View as DefinitionPopupState,
            {
                setPopupState: (_, { state }) => state,
            },
        ],
    },
    loaders: ({ values, props, actions }) => ({
        definition: [
            null as TaxonomicDefinitionTypes | null,
            {
                setDefinition: ({ item }) => ({ ...values.definition, ...item } as TaxonomicDefinitionTypes),
                handleCancel: () => {
                    // Reset to original definition
                    actions.setPopupState(DefinitionPopupState.View)
                    return props.item
                },
                handleSave: async (_, breakpoint) => {
                    await breakpoint(100)

                    if (!values.definition) {
                        return null
                    }

                    let definition = values.definition
                    try {
                        if (values.isAction) {
                            // Action Definitions
                            const _action = values.definition as ActionType
                            definition = await api.actions.update(_action.id, _action)
                            actionsModel.actions.updateAction(definition as ActionType)
                        } else if (values.isEvent) {
                            // Event Definitions
                            const _event = values.definition as EventDefinition
                            definition = await api.update(
                                `api/projects/@current/event_definitions/${_event.id}`,
                                _event
                            )
                            eventDefinitionsModel.actions.updateEventDefinition(definition as EventDefinition)
                        } else if (values.type === TaxonomicFilterGroupType.EventProperties) {
                            // Event Property Definitions
                            const _eventProperty = values.definition as PropertyDefinition
                            definition = await api.update(
                                `api/projects/@current/property_definitions/${_eventProperty.id}`,
                                _eventProperty
                            )
                            propertyDefinitionsModel.actions.updatePropertyDefinition(definition as PropertyDefinition)
                        } else if (values.type === TaxonomicFilterGroupType.Cohorts) {
                            // Cohort
                            const _cohort = values.definition as CohortType
                            definition = await api.cohorts.update(_cohort.id, _cohort)
                            cohortsModel.actions.updateCohort(definition as CohortType)
                        }
                    } catch (error) {
                        errorToast(
                            'Error saving your definition',
                            'Attempting to save this definition returned an error:',
                            error
                        )
                    }
                    breakpoint()
                    // Disregard save attempts for any other types of taxonomy groups
                    toast(`${capitalizeFirstLetter(values.singularType)} definition saved`)
                    actions.setPopupState(DefinitionPopupState.View)
                    return values.definition
                },
            },
        ],
    }),
    selectors: {
        type: [() => [(_, props) => props.type], (type) => type],
        singularType: [(s) => [s.type], (type) => getSingularType(type)],
        hasTaxonomyFeatures: [
            () => [(_, props) => props.hasTaxonomyFeatures],
            (hasTaxonomyFeatures) => hasTaxonomyFeatures,
        ],
        isViewable: [
            (s) => [s.type],
            (type) =>
                [
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.CustomEvents,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.EventProperties,
                ].includes(type),
        ],
        isAction: [(s) => [s.type], (type) => type === TaxonomicFilterGroupType.Actions],
        isEvent: [
            (s) => [s.type],
            (type) => [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.CustomEvents].includes(type),
        ],
        isProperty: [
            (s) => [s.type],
            (type) =>
                [TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.EventProperties].includes(type) ||
                type.startsWith(TaxonomicFilterGroupType.GroupsPrefix),
        ],
        isCohort: [(s) => [s.type], (type) => type === TaxonomicFilterGroupType.Cohorts],
        isElement: [(s) => [s.type], (type) => type === TaxonomicFilterGroupType.Elements],
    },
    listeners: ({ actions, selectors, values }) => ({
        setDefinition: (_, __, ___, previousState) => {
            // Reset definition popup to view mode if context is switched
            if (values.definition?.name !== selectors.definition(previousState)?.name) {
                actions.setPopupState(DefinitionPopupState.View)
            }
        },
        setNewTag: async ({ tag }, breakpoint) => {
            if (!values.definition || !('tags' in values.definition)) {
                return
            }
            await breakpoint(100)
            const _definition = values.definition as EventDefinition | PropertyDefinition | ActionType
            if (_definition.tags?.includes(tag)) {
                errorToast('Oops! This tag is already set', `This ${values.singularType} already includes this tag.`)
                return
            }
            actions.setDefinition({ tags: _definition?.tags ? [..._definition.tags, tag] : [tag] })
        },
        deleteTag: async ({ tag }, breakpoint) => {
            if (!values.definition || !('tags' in values.definition)) {
                return
            }
            await breakpoint(100)
            const _definition = values.definition as EventDefinition | PropertyDefinition | ActionType
            actions.setDefinition({ tags: _definition.tags?.filter((_tag: string) => _tag !== tag) || [] })
        },
        handleView: () => {
            // Redirect to the correct full definition page
            if (values.isAction) {
                // Action Definitions
                router.actions.push(urls.action((values.definition as ActionType).id))
            } else if (values.isEvent) {
                // Event Definitions
                router.actions.push(urls.eventStat((values.definition as EventDefinition).id))
            } else if (values.isProperty) {
                // Property Definitions
                router.actions.push(urls.eventPropertyStat((values.definition as PropertyDefinition).id))
            } else if (values.isCohort) {
                // Cohort
                router.actions.push(urls.cohort((values.definition as CohortType).id))
            }
        },
        handleSave: () => {
            actions.setPopupState(DefinitionPopupState.View)
        },
    }),
})
