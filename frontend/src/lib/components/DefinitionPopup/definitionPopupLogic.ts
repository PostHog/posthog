import { kea } from 'kea'
import type { definitionPopupLogicType } from './definitionPopupLogicType'
import { TaxonomicDefinitionTypes, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { capitalizeFirstLetter } from 'lib/utils'
import { getSingularType } from 'lib/components/DefinitionPopup/utils'
import { ActionType, AvailableFeature, CohortType, EventDefinition, PropertyDefinition } from '~/types'
import { urls } from 'scenes/urls'
import api from 'lib/api'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { actionsModel } from '~/models/actionsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import equal from 'fast-deep-equal'
import { userLogic } from 'scenes/userLogic'
import { lemonToast } from '../lemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export enum DefinitionPopupState {
    Edit = 'edit',
    View = 'view',
}

export interface DefinitionPopupLogicProps {
    /* String type accounts for types with `TaxonomicFilterGroupType.GroupsPrefix` prefix */
    type: TaxonomicFilterGroupType | string
    /* Callback to update specific item in in-memory list */
    updateRemoteItem?: (item: TaxonomicDefinitionTypes) => void
    onMouseLeave?: () => void
    onCancel?: () => void
    onSave?: () => void
    hideView?: boolean
    hideEdit?: boolean
    openDetailInNewTab?: boolean
}

export const definitionPopupLogic = kea<definitionPopupLogicType>({
    props: {} as DefinitionPopupLogicProps,
    connect: {
        values: [userLogic, ['hasAvailableFeature']],
    },
    path: ['lib', 'components', 'DefinitionPanel', 'definitionPopupLogic'],
    actions: {
        setDefinition: (item: Partial<TaxonomicDefinitionTypes>) => ({ item }),
        setLocalDefinition: (item: Partial<TaxonomicDefinitionTypes>) => ({ item }),
        setPopupState: (state: DefinitionPopupState) => ({ state }),
        handleCancel: true,
        recordHoverActivity: true,
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
    loaders: ({ values, props, cache }) => ({
        definition: [
            {} as Partial<TaxonomicDefinitionTypes>,
            {
                setDefinition: ({ item }) => item as TaxonomicDefinitionTypes,
                handleSave: async (_, breakpoint) => {
                    if (!values.definition) {
                        return {}
                    }

                    let definition = {
                        ...values.definition,
                        ...values.localDefinition,
                    } as TaxonomicDefinitionTypes
                    cache.startTime = performance.now()
                    try {
                        if (values.isAction) {
                            // Action Definitions
                            const _action = definition as ActionType
                            definition = await api.update(`api/projects/@current/actions/${_action.id}`, _action)
                            actionsModel.findMounted()?.actions.updateAction(definition as ActionType)
                        } else if (values.isEvent) {
                            // Event Definitions
                            const _event = definition as EventDefinition
                            definition = await api.update(`api/projects/@current/event_definitions/${_event.id}`, {
                                ..._event,
                                owner: _event.owner?.id ?? null,
                                verified: !!_event.verified,
                            })
                            eventDefinitionsModel
                                .findMounted()
                                ?.actions.updateEventDefinition(definition as EventDefinition)
                        } else if (
                            values.type === TaxonomicFilterGroupType.EventProperties ||
                            values.type === TaxonomicFilterGroupType.EventFeatureFlags
                        ) {
                            // Event Property Definitions
                            const _eventProperty = definition as PropertyDefinition
                            definition = await api.update(
                                `api/projects/@current/property_definitions/${_eventProperty.id}`,
                                _eventProperty
                            )
                            propertyDefinitionsModel
                                .findMounted()
                                ?.actions.updatePropertyDefinition(definition as PropertyDefinition)
                        } else if (values.type === TaxonomicFilterGroupType.Cohorts) {
                            // Cohort
                            const _cohort = definition as CohortType
                            definition = await api.update(`api/projects/@current/cohorts/${_cohort.id}`, _cohort)
                            cohortsModel.findMounted()?.actions.updateCohort(definition as CohortType)
                        }
                    } catch (error: any) {
                        lemonToast.error(error.message)
                    }
                    breakpoint()
                    // Disregard save attempts for any other types of taxonomy groups
                    lemonToast.success(`${capitalizeFirstLetter(values.singularType)} definition saved`)
                    // Update item in infinite list
                    props.updateRemoteItem?.(definition)
                    return definition
                },
            },
        ],
    }),
    selectors: {
        type: [() => [(_, props) => props.type], (type) => type],
        onMouseLeave: [() => [(_, props) => props.onMouseLeave], (onMouseLeave) => onMouseLeave],
        hideView: [() => [(_, props) => props.hideView], (hideView) => hideView ?? false],
        hideEdit: [() => [(_, props) => props.hideEdit], (hideEdit) => hideEdit ?? false],
        openDetailInNewTab: [
            () => [(_, props) => props.openDetailInNewTab],
            (openDetailInNewTab) => openDetailInNewTab ?? true,
        ],
        singularType: [
            (s) => [s.type],
            (type) =>
                getSingularType(
                    type,
                    !!featureFlagLogic.findMounted()?.values?.featureFlags?.[FEATURE_FLAGS.SIMPLIFY_ACTIONS]
                ),
        ],
        dirty: [
            (s) => [s.state, s.definition, s.localDefinition],
            (state, definition, localDefinition) =>
                state === DefinitionPopupState.Edit && !equal(definition, localDefinition),
        ],
        hasTaxonomyFeatures: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) =>
                hasAvailableFeature(AvailableFeature.INGESTION_TAXONOMY) ||
                hasAvailableFeature(AvailableFeature.TAGGING),
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
                    TaxonomicFilterGroupType.EventFeatureFlags,
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
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.NumericalEventProperties,
                ].includes(type) || type.startsWith(TaxonomicFilterGroupType.GroupsPrefix),
        ],
        isCohort: [(s) => [s.type], (type) => type === TaxonomicFilterGroupType.Cohorts],
        isElement: [(s) => [s.type], (type) => type === TaxonomicFilterGroupType.Elements],
        viewFullDetailUrl: [
            (s) => [s.definition, s.isAction, s.isEvent, s.isProperty, s.isCohort],
            (definition, isAction, isEvent, isProperty, isCohort) => {
                if (isAction) {
                    // Action Definitions
                    return urls.action((definition as ActionType).id)
                } else if (isEvent) {
                    // Event Definitions
                    return urls.eventDefinition((definition as EventDefinition).id)
                } else if (isProperty) {
                    // Property Definitions
                    return urls.eventPropertyDefinition((definition as PropertyDefinition).id)
                } else if (isCohort) {
                    // Cohort
                    return urls.cohort((definition as CohortType).id)
                }
                return undefined
            },
        ],
    },
    listeners: ({ actions, selectors, values, props, cache }) => ({
        setDefinition: (_, __, ___, previousState) => {
            // Reset definition popup to view mode if context is switched
            if (
                selectors.definition(previousState)?.name &&
                values.definition?.name !== selectors.definition(previousState).name
            ) {
                actions.setPopupState(DefinitionPopupState.View)
                actions.recordHoverActivity()
            }
        },
        handleSave: () => {
            actions.setPopupState(DefinitionPopupState.View)
            props?.onSave?.()
        },
        handleSaveSuccess: () => {
            if (cache.startTime !== undefined) {
                eventUsageLogic
                    .findMounted()
                    ?.actions?.reportDataManagementDefinitionSaveSucceeded(
                        values.type,
                        performance.now() - cache.startTime
                    )
                cache.startTime = undefined
            }
        },
        handleSaveFailure: ({ error }) => {
            if (cache.startTime !== undefined) {
                eventUsageLogic
                    .findMounted()
                    ?.actions?.reportDataManagementDefinitionSaveFailed(
                        values.type,
                        performance.now() - cache.startTime,
                        error
                    )
                cache.startTime = undefined
            }
        },
        handleCancel: () => {
            actions.setPopupState(DefinitionPopupState.View)
            actions.setLocalDefinition(values.definition)
            props?.onCancel?.()
            eventUsageLogic.findMounted()?.actions?.reportDataManagementDefinitionCancel(values.type)
        },
        recordHoverActivity: async (_, breakpoint) => {
            await breakpoint(IS_TEST_MODE ? 1 : 1000) // Tests will wait for all breakpoints to finish
            eventUsageLogic.findMounted()?.actions?.reportDataManagementDefinitionHovered(values.type)
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.recordHoverActivity()
        },
    }),
})
