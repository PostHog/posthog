import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { schemaManagementLogic } from '../schema/schemaManagementLogic'
import type { SchemaPropertyGroup } from '../schema/schemaManagementLogic'
import type { eventDefinitionSchemaLogicType } from './eventDefinitionSchemaLogicType'

export type { SchemaPropertyGroup }

export interface EventSchema {
    id: string
    event_definition: string
    property_group: SchemaPropertyGroup
    created_at: string
    updated_at: string
}

export interface EventDefinitionSchemaLogicProps {
    eventDefinitionId: string
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
    reducers({
        eventSchemas: {
            removePropertyGroup: (state, { eventSchemaId }) =>
                state.filter((schema: EventSchema) => schema.id !== eventSchemaId),
        },
    }),
    selectors({
        availablePropertyGroups: [
            (s) => [s.allPropertyGroups, s.eventSchemas],
            (allPropertyGroups: SchemaPropertyGroup[], eventSchemas: EventSchema[]): SchemaPropertyGroup[] => {
                const usedGroupIds = new Set(eventSchemas.map((schema: EventSchema) => schema.property_group.id))
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
                // Reload to get the updated list from server
                await actions.loadEventSchemas()
                lemonToast.success('Property group added to event schema')
            } catch (error: any) {
                const errorMessage = error.detail || error.message || 'Unknown error'
                lemonToast.error(`Failed to add property group: ${errorMessage}`)
            }
        },
        removePropertyGroup: async ({ eventSchemaId }) => {
            try {
                await api.eventSchemas.delete(eventSchemaId)
                // The reducer already handles removing from state
                lemonToast.success('Property group removed from event schema')
            } catch (error: any) {
                lemonToast.error(`Failed to remove property group: ${error.detail || error.message}`)
            }
        },
        // Listen for property group updates from schemaManagementLogic
        updatePropertyGroupSuccess: async ({ propertyGroups }) => {
            // Check if any of the updated property groups are used in our event schemas
            const usedGroupIds = new Set(values.eventSchemas.map((schema: EventSchema) => schema.property_group.id))
            const wasUpdated = propertyGroups.some((group: SchemaPropertyGroup) => usedGroupIds.has(group.id))

            if (wasUpdated) {
                // Reload event schemas to get fresh embedded property group data
                await actions.loadEventSchemas()
            }
            // Always reload all property groups to ensure we have the latest list
            await actions.loadAllPropertyGroups()
        },
        createPropertyGroupSuccess: async () => {
            // Reload property groups to include the new one in available list
            await actions.loadAllPropertyGroups()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadEventSchemas()
        actions.loadAllPropertyGroups()
    }),
])
