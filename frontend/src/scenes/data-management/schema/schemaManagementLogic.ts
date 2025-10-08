import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { schemaManagementLogicType } from './schemaManagementLogicType'

export type PropertyType = 'String' | 'Numeric' | 'Boolean' | 'DateTime' | 'Duration'

export interface SchemaPropertyGroupProperty {
    id: string
    name: string
    property_type: PropertyType
    is_required: boolean
    description: string
    order: number
}

export interface EventDefinitionBasic {
    id: string
    name: string
}

export interface SchemaPropertyGroup {
    id: string
    name: string
    description: string
    properties: SchemaPropertyGroupProperty[]
    events: EventDefinitionBasic[]
    created_at: string
    updated_at: string
}

export interface SchemaManagementLogicProps {
    key?: string
}

export const schemaManagementLogic = kea<schemaManagementLogicType>([
    path(['scenes', 'data-management', 'schema', 'schemaManagementLogic']),
    props({} as SchemaManagementLogicProps),
    key((props) => props.key || 'default'),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setPropertyGroupModalOpen: (open: boolean) => ({ open }),
        setEditingPropertyGroup: (propertyGroup: SchemaPropertyGroup | null) => ({ propertyGroup }),
        deletePropertyGroup: (id: string) => ({ id }),
    }),
    loaders(({ values }) => ({
        propertyGroups: [
            [] as SchemaPropertyGroup[],
            {
                loadPropertyGroups: async () => {
                    const response = await api.get(`api/projects/@current/schema_property_groups/`)
                    return response.results || response || []
                },
                createPropertyGroup: async (data: Partial<SchemaPropertyGroup>) => {
                    try {
                        const response = await api.create(`api/projects/@current/schema_property_groups/`, data)
                        lemonToast.success('Property group created')
                        return [response, ...values.propertyGroups]
                    } catch {
                        lemonToast.error('Failed to create property group')
                        throw new Error('Failed to create property group')
                    }
                },
                updatePropertyGroup: async ({ id, data }: { id: string; data: Partial<SchemaPropertyGroup> }) => {
                    try {
                        const response = await api.update(`api/projects/@current/schema_property_groups/${id}/`, data)
                        lemonToast.success('Property group updated')
                        return values.propertyGroups.map((pg) => (pg.id === id ? response : pg))
                    } catch {
                        lemonToast.error('Failed to update property group')
                        throw new Error('Failed to update property group')
                    }
                },
            },
        ],
    })),
    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        propertyGroupModalOpen: [
            false,
            {
                setPropertyGroupModalOpen: (_, { open }) => open,
            },
        ],
        editingPropertyGroup: [
            null as SchemaPropertyGroup | null,
            {
                setEditingPropertyGroup: (_, { propertyGroup }) => propertyGroup,
                setPropertyGroupModalOpen: (state, { open }) => (open ? state : null),
            },
        ],
    }),
    selectors({
        filteredPropertyGroups: [
            (s) => [s.propertyGroups, s.searchTerm],
            (propertyGroups, searchTerm): SchemaPropertyGroup[] => {
                if (!searchTerm) {
                    return propertyGroups
                }
                const lowerSearchTerm = searchTerm.toLowerCase()
                return propertyGroups.filter(
                    (pg) =>
                        pg.name.toLowerCase().includes(lowerSearchTerm) ||
                        pg.description.toLowerCase().includes(lowerSearchTerm) ||
                        pg.properties.some((prop) => prop.name.toLowerCase().includes(lowerSearchTerm))
                )
            },
        ],
    }),
    listeners(({ actions }) => ({
        deletePropertyGroup: async ({ id }) => {
            try {
                await api.delete(`api/projects/@current/schema_property_groups/${id}/`)
                actions.loadPropertyGroups()
                lemonToast.success('Property group deleted')
            } catch {
                lemonToast.error('Failed to delete property group')
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPropertyGroups()
    }),
])
