import equal from 'fast-deep-equal'
import { actions, connect, events, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getSingularType } from 'lib/components/DefinitionPopover/utils'
import { TaxonomicDefinitionTypes, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { capitalizeFirstLetter } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { updatePropertyDefinitions } from '~/models/propertyDefinitionsModel'
import { ActionType, AvailableFeature, CohortType, EventDefinition, PropertyDefinition } from '~/types'

import type { definitionPopoverLogicType } from './definitionPopoverLogicType'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export enum DefinitionPopoverState {
    Edit = 'edit',
    View = 'view',
}

export interface DefinitionPopoverLogicProps {
    /* String type accounts for types with `TaxonomicFilterGroupType.GroupsPrefix` prefix */
    type: TaxonomicFilterGroupType | string
    /* Callback to update specific item in in-memory list */
    updateRemoteItem?: (item: TaxonomicDefinitionTypes) => void
    onCancel?: () => void
    onSave?: () => void
    hideView?: boolean
    hideEdit?: boolean
    openDetailInNewTab?: boolean
}

export const definitionPopoverLogic = kea<definitionPopoverLogicType>([
    props({} as DefinitionPopoverLogicProps),
    path(['lib', 'components', 'DefinitionPanel', 'definitionPopoverLogic']),
    connect(() => ({
        values: [userLogic, ['hasAvailableFeature']],
    })),
    actions(({ values }) => ({
        setDefinition: (item: Partial<TaxonomicDefinitionTypes>) => ({ item, isDataWarehouse: values.isDataWarehouse }),
        setLocalDefinition: (item: Partial<TaxonomicDefinitionTypes>) => ({ item }),
        setPopoverState: (state: DefinitionPopoverState) => ({ state }),
        handleCancel: true,
        recordHoverActivity: true,
    })),
    loaders(({ values, props, cache }) => ({
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
                            updatePropertyDefinitions({
                                [`event/${definition.name}`]: definition as PropertyDefinition,
                            })
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
    })),
    reducers({
        state: [
            DefinitionPopoverState.View as DefinitionPopoverState,
            {
                setPopoverState: (_, { state }) => state,
            },
        ],
        localDefinition: [
            {} as Partial<TaxonomicDefinitionTypes>,
            {
                setDefinition: (_, { item, isDataWarehouse }) => {
                    if (isDataWarehouse && 'fields' in item) {
                        // Pre-populate the data warehouse table settings for insights
                        const warehouseItem = item as DataWarehouseTableForInsight

                        if (!('id_field' in item)) {
                            const idField = Object.values(warehouseItem.fields).find((n) => n.name === 'id')
                            if (idField) {
                                warehouseItem['id_field'] = idField.name
                            }
                        }

                        if (!('distinct_id_field' in item)) {
                            const distinctIdField =
                                Object.values(warehouseItem.fields).find((n) => n.name === 'distinct_id') ??
                                Object.values(warehouseItem.fields).find((n) => n.name === 'id')
                            if (distinctIdField) {
                                warehouseItem['distinct_id_field'] = distinctIdField.name
                            }
                        }

                        if (!('timestamp_field' in item)) {
                            const timestampKeys = [
                                'created',
                                'created_at',
                                'createdAt',
                                'updated',
                                'updated_at',
                                'updatedAt',
                            ]
                            const timestampNameField = Object.values(warehouseItem.fields).find((n) =>
                                timestampKeys.includes(n.name)
                            )
                            const timestampTypeField = Object.values(warehouseItem.fields).find(
                                (n) => n.type == 'datetime' || n.type == 'date'
                            )
                            if (timestampNameField || timestampTypeField) {
                                warehouseItem['timestamp_field'] = timestampNameField?.name || timestampTypeField?.name
                            }
                        }

                        return warehouseItem
                    }

                    return item
                },
                setLocalDefinition: (state, { item }) =>
                    ({
                        ...state,
                        ...item,
                    }) as Partial<TaxonomicDefinitionTypes>,
            },
        ],
    }),
    selectors({
        type: [() => [(_, props) => props.type], (type) => type],
        hideView: [() => [(_, props) => props.hideView], (hideView) => hideView ?? false],
        hideEdit: [() => [(_, props) => props.hideEdit], (hideEdit) => hideEdit ?? false],
        openDetailInNewTab: [
            () => [(_, props) => props.openDetailInNewTab],
            (openDetailInNewTab) => openDetailInNewTab ?? true,
        ],
        singularType: [(s) => [s.type], (type) => getSingularType(type)],
        dirty: [
            (s) => [s.state, s.definition, s.localDefinition],
            (state, definition, localDefinition) =>
                state === DefinitionPopoverState.Edit && !equal(definition, localDefinition),
        ],
        hasTaxonomyFeatures: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) =>
                hasAvailableFeature(AvailableFeature.INGESTION_TAXONOMY) ||
                hasAvailableFeature(AvailableFeature.TAGGING),
        ],
        isViewable: [
            (s) => [s.type],
            (type) => {
                if (
                    type === TaxonomicFilterGroupType.PersonProperties ||
                    type.startsWith(TaxonomicFilterGroupType.GroupsPrefix)
                ) {
                    return true
                }

                return [
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.CustomEvents,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                ].includes(type)
            },
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
                    TaxonomicFilterGroupType.SessionProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.NumericalEventProperties,
                    TaxonomicFilterGroupType.Metadata,
                    TaxonomicFilterGroupType.DataWarehousePersonProperties,
                    TaxonomicFilterGroupType.RevenueAnalyticsProperties,
                    TaxonomicFilterGroupType.ErrorTrackingProperties,
                ].includes(type) || type.startsWith(TaxonomicFilterGroupType.GroupsPrefix),
        ],
        isVirtual: [
            (s) => [s.definition],
            (definition) => {
                return 'virtual' in definition && definition.virtual
            },
        ],
        hasSentAs: [
            (s) => [s.type, s.isProperty, s.isEvent, s.isVirtual],
            (type, isProperty, isEvent, isVirtual) =>
                isEvent || (isProperty && !isVirtual && type !== TaxonomicFilterGroupType.SessionProperties),
        ],
        isCohort: [(s) => [s.type], (type) => type === TaxonomicFilterGroupType.Cohorts],
        isDataWarehouse: [(s) => [s.type], (type) => type === TaxonomicFilterGroupType.DataWarehouse],
        isDataWarehousePersonProperty: [
            (s) => [s.type],
            (type) => type === TaxonomicFilterGroupType.DataWarehousePersonProperties,
        ],
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
                    return urls.propertyDefinition((definition as PropertyDefinition).id)
                } else if (isCohort) {
                    // Cohort
                    return urls.cohort((definition as CohortType).id)
                }
                return undefined
            },
        ],
    }),
    listeners(({ actions, selectors, values, props, cache }) => ({
        setDefinition: (_, __, ___, previousState) => {
            // Reset definition popover to view mode if context is switched
            if (
                selectors.definition(previousState)?.name &&
                values.definition?.name !== selectors.definition(previousState).name
            ) {
                actions.setPopoverState(DefinitionPopoverState.View)
                actions.recordHoverActivity()
            }
        },
        handleSave: () => {
            actions.setPopoverState(DefinitionPopoverState.View)
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
            actions.setPopoverState(DefinitionPopoverState.View)
            actions.setLocalDefinition(values.definition)
            props?.onCancel?.()
            eventUsageLogic.findMounted()?.actions?.reportDataManagementDefinitionCancel(values.type)
        },
        recordHoverActivity: async (_, breakpoint) => {
            await breakpoint(IS_TEST_MODE ? 1 : 1000) // Tests will wait for all breakpoints to finish
            eventUsageLogic.findMounted()?.actions?.reportDataManagementDefinitionHovered(values.type)
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.recordHoverActivity()
        },
    })),
])
