import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { SchemaEnforcementMode } from '~/types'

import { type SchemaPropertyGroup, schemaManagementLogic } from '../schema/schemaManagementLogic'
import type { eventDefinitionSchemaLogicType } from './eventDefinitionSchemaLogicType'

export type { SchemaPropertyGroup }

function getErrorMessage(error: any, defaultMessage: string): string {
    if (error.detail) {
        const detail = error.detail

        // Handle "property group is already added to this event schema"
        if (
            typeof detail === 'string' &&
            (detail.includes('already added to this event schema') || detail.includes('already exists'))
        ) {
            // Extract property group name if available
            const nameMatch = detail.match(/Property group '([^']+)'/)
            if (nameMatch) {
                return `Property group "${nameMatch[1]}" is already added to this event`
            }
            return detail
        }

        // Handle team mismatch errors
        if (typeof detail === 'string' && detail.includes('must belong to the same team')) {
            return 'Property group must belong to the same team as the event'
        }

        // Return the detail if it's a user-friendly string
        if (typeof detail === 'string' && !detail.includes('IntegrityError') && !detail.includes('Key (')) {
            return detail
        }
    }

    if (error.message && !error.message.includes('IntegrityError')) {
        return error.message
    }

    return defaultMessage
}

export interface EventSchema {
    id: string
    event_definition: string
    property_group_id: string
    property_group: SchemaPropertyGroup
    created_at: string
    updated_at: string
}

export interface EventDefinitionSchemaLogicProps {
    eventDefinitionId: string
    enforcementMode: SchemaEnforcementMode
}

export const eventDefinitionSchemaLogic = kea<eventDefinitionSchemaLogicType>([
    path(['scenes', 'data-management', 'events', 'eventDefinitionSchemaLogic']),
    props({} as EventDefinitionSchemaLogicProps),
    key((props) => props.eventDefinitionId),
    connect((props: EventDefinitionSchemaLogicProps) => ({
        actions: [
            schemaManagementLogic({ key: `event-${props.eventDefinitionId}` }),
            ['updatePropertyGroupSuccess', 'createPropertyGroupSuccess'],
        ],
    })),
    actions({
        addPropertyGroup: (propertyGroupId: string) => ({ propertyGroupId }),
        removePropertyGroup: (eventSchemaId: string) => ({ eventSchemaId }),
        updateSchemaEnforcementMode: (mode: SchemaEnforcementMode) => ({ mode }),
        updateSchemaEnforcementModeSuccess: (mode: SchemaEnforcementMode) => ({ mode }),
        setSchemaEnforcementModeUpdating: (updating: boolean) => ({ updating }),
    }),
    loaders(({ props }) => ({
        eventSchemas: {
            __default: [] as EventSchema[],
            loadEventSchemas: async () => {
                const response = await api.eventSchemas.list(props.eventDefinitionId)
                return response.results || []
            },
        },
        allPropertyGroups: {
            __default: [] as SchemaPropertyGroup[],
            loadAllPropertyGroups: async () => {
                const response = await api.schemaPropertyGroups.list()
                return response.results || []
            },
        },
    })),
    reducers(({ props }) => ({
        eventSchemas: [
            [] as EventSchema[],
            {
                removePropertyGroup: (state, { eventSchemaId }) =>
                    state.filter((schema: EventSchema) => schema.id !== eventSchemaId),
            },
        ],
        schemaEnforcementMode: [
            (props.enforcementMode ?? SchemaEnforcementMode.Allow) as SchemaEnforcementMode,
            {
                updateSchemaEnforcementModeSuccess: (_, { mode }) => mode,
            },
        ],
        schemaEnforcementModeUpdating: [
            false,
            {
                setSchemaEnforcementModeUpdating: (_, { updating }) => updating,
            },
        ],
    })),
    selectors({
        availablePropertyGroups: [
            (s) => [s.allPropertyGroups, s.eventSchemas],
            (allPropertyGroups: SchemaPropertyGroup[], eventSchemas: EventSchema[]): SchemaPropertyGroup[] => {
                const usedGroupIds = new Set(eventSchemas.map((schema: EventSchema) => schema.property_group_id))
                return allPropertyGroups.filter((group: SchemaPropertyGroup) => !usedGroupIds.has(group.id))
            },
        ],
    }),
    listeners(({ actions, props, values }) => ({
        addPropertyGroup: async ({ propertyGroupId }) => {
            try {
                await api.eventSchemas.create({
                    event_definition: props.eventDefinitionId,
                    property_group_id: propertyGroupId,
                })
                await actions.loadEventSchemas()
                lemonToast.success('Property group added to event schema')
            } catch (error: any) {
                const errorMessage = getErrorMessage(error, 'Failed to add property group')
                lemonToast.error(errorMessage)
            }
        },
        removePropertyGroup: async ({ eventSchemaId }) => {
            try {
                await api.eventSchemas.delete(eventSchemaId)
                lemonToast.success('Property group removed from event schema')
            } catch (error: any) {
                const errorMessage = getErrorMessage(error, 'Failed to remove property group')
                lemonToast.error(errorMessage)
            }
        },
        updateSchemaEnforcementMode: async ({ mode }) => {
            if (values.eventSchemas.length === 0) {
                lemonToast.info('Add a property group first to enable schema enforcement')
                return
            }

            actions.setSchemaEnforcementModeUpdating(true)
            try {
                await api.eventDefinitions.update({
                    eventDefinitionId: props.eventDefinitionId,
                    eventDefinitionData: { enforcement_mode: mode },
                })
                actions.updateSchemaEnforcementModeSuccess(mode)
                if (mode === SchemaEnforcementMode.Reject) {
                    lemonToast.success('Schema enforcement enabled. Events that fail validation will be rejected.')
                } else {
                    lemonToast.success('Schema enforcement disabled. All events will be accepted.')
                }
            } catch (error: any) {
                const errorMessage = getErrorMessage(error, 'Failed to update schema enforcement mode')
                lemonToast.error(errorMessage)
            } finally {
                actions.setSchemaEnforcementModeUpdating(false)
            }
        },
        updatePropertyGroupSuccess: async () => {
            await actions.loadEventSchemas()
        },
        createPropertyGroupSuccess: async () => {
            await actions.loadEventSchemas()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadEventSchemas()
        actions.loadAllPropertyGroups()
    }),
])
