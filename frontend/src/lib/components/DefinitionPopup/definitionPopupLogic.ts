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
import equal from 'fast-deep-equal'

export enum DefinitionPopupState {
    Edit = 'edit',
    View = 'view',
}

export interface DefinitionPopupLogicProps {
    /* String type accounts for types with `TaxonomicFilterGroupType.GroupsPrefix` prefix */
    type: TaxonomicFilterGroupType | string
    hasTaxonomyFeatures?: boolean
    /* Callback to update specific item in in-memory list */
    updateRemoteItem?: (item: Partial<TaxonomicDefinitionTypes>) => void
}

export const definitionPopupLogic = kea<definitionPopupLogicType<DefinitionPopupLogicProps, DefinitionPopupState>>({
    props: {} as DefinitionPopupLogicProps,
    path: ['lib', 'components', 'DefinitionPanel', 'definitionPopupLogic'],
    actions: {
        setDefinition: (item: Partial<TaxonomicDefinitionTypes>) => ({ item }),
        setLocalDefinition: (item: Partial<TaxonomicDefinitionTypes>) => ({ item }),
        setPopupState: (state: DefinitionPopupState) => ({ state }),
        setNewTag: (tag: string) => ({ tag }),
        deleteTag: (tag: string) => ({ tag }),
        handleView: true,
        handleCancel: true,
    },
    reducers: {
        state: [
            DefinitionPopupState.View as DefinitionPopupState,
            {
                setPopupState: (_, { state }) => state,
            },
        ],
        localDefinition: [
            {} as Partial<TaxonomicDefinitionTypes>,
            {
                setDefinition: (_, { item }) => item,
                setLocalDefinition: (state, { item }) => ({ ...state, ...item } as Partial<TaxonomicDefinitionTypes>),
            },
        ],
    },
    loaders: ({ values, actions, props }) => ({
        definition: [
            {} as Partial<TaxonomicDefinitionTypes>,
            {
                setDefinition: ({ item }) => item as TaxonomicDefinitionTypes,
                handleSave: async (_, breakpoint) => {
                    await breakpoint(100)

                    if (!values.definition) {
                        return {}
                    }

                    let definition = {
                        ...values.definition,
                        ...values.localDefinition,
                    } as Partial<TaxonomicDefinitionTypes>
                    try {
                        if (values.isAction) {
                            // Action Definitions
                            const _action = definition as ActionType
                            definition = await api.update(`api/projects/@current/actions/${_action.id}`, _action)
                            actionsModel?.isMounted() && actionsModel.actions.updateAction(definition as ActionType)
                        } else if (values.isEvent) {
                            // Event Definitions
                            const _event = definition as EventDefinition
                            definition = await api.update(`api/projects/@current/event_definitions/${_event.id}`, {
                                ..._event,
                                owner: _event.owner?.id ?? null,
                            })
                            eventDefinitionsModel?.isMounted() &&
                                eventDefinitionsModel.actions.updateEventDefinition(definition as EventDefinition)
                        } else if (values.type === TaxonomicFilterGroupType.EventProperties) {
                            // Event Property Definitions
                            const _eventProperty = definition as PropertyDefinition
                            definition = await api.update(
                                `api/projects/@current/property_definitions/${_eventProperty.id}`,
                                _eventProperty
                            )
                            propertyDefinitionsModel?.isMounted() &&
                                propertyDefinitionsModel.actions.updatePropertyDefinition(
                                    definition as PropertyDefinition
                                )
                        } else if (values.type === TaxonomicFilterGroupType.Cohorts) {
                            // Cohort
                            const _cohort = definition as CohortType
                            definition = await api.update(`api/projects/@current/cohorts/${_cohort.id}`, _cohort)
                            cohortsModel?.isMounted() && cohortsModel.actions.updateCohort(definition as CohortType)
                        }
                    } catch (error) {
                        errorToast(
                            'Error saving your definition',
                            'Attempting to save this definition returned an error:',
                            error.message
                        )
                    }
                    breakpoint()
                    // Disregard save attempts for any other types of taxonomy groups
                    toast(`${capitalizeFirstLetter(values.singularType)} definition saved`)
                    actions.setPopupState(DefinitionPopupState.View)
                    // Update item in infinite list
                    props.updateRemoteItem?.(definition)
                    return definition
                },
            },
        ],
    }),
    selectors: {
        type: [() => [(_, props) => props.type], (type) => type],
        singularType: [(s) => [s.type], (type) => getSingularType(type)],
        dirty: [
            (s) => [s.state, s.definition, s.localDefinition],
            (state, definition, localDefinition) =>
                state === DefinitionPopupState.Edit && !equal(definition, localDefinition),
        ],
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
                [
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.NumericalEventProperties,
                ].includes(type) || type.startsWith(TaxonomicFilterGroupType.GroupsPrefix),
        ],
        isCohort: [(s) => [s.type], (type) => type === TaxonomicFilterGroupType.Cohorts],
        isElement: [(s) => [s.type], (type) => type === TaxonomicFilterGroupType.Elements],
    },
    listeners: ({ actions, selectors, values }) => ({
        setDefinition: (_, __, ___, previousState) => {
            // Reset definition popup to view mode if context is switched
            if (
                selectors.definition(previousState)?.name &&
                values.definition?.name !== selectors.definition(previousState).name
            ) {
                actions.setPopupState(DefinitionPopupState.View)
            }
        },
        setNewTag: async ({ tag }) => {
            if (!values.definition || !('tags' in values.definition)) {
                return
            }
            const _definition = values.localDefinition as EventDefinition | PropertyDefinition | ActionType
            if (_definition.tags?.includes(tag)) {
                errorToast('Oops! This tag is already set', `This ${values.singularType} already includes this tag.`)
                return
            }
            actions.setLocalDefinition({ tags: _definition?.tags ? [..._definition.tags, tag] : [tag] })
        },
        deleteTag: async ({ tag }) => {
            if (!values.definition || !('tags' in values.definition)) {
                return
            }
            const _definition = values.localDefinition as EventDefinition | PropertyDefinition | ActionType
            actions.setLocalDefinition({ tags: _definition.tags?.filter((_tag: string) => _tag !== tag) || [] })
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
        handleCancel: () => {
            actions.setPopupState(DefinitionPopupState.View)
            actions.setLocalDefinition(values.definition)
        },
    }),
})
