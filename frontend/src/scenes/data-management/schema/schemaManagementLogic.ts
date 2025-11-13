import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { schemaManagementLogicType } from './schemaManagementLogicType'

export type PropertyType = 'String' | 'Numeric' | 'Boolean' | 'DateTime' | 'Object'

export const PROPERTY_TYPE_OPTIONS: { value: PropertyType; label: string }[] = [
    { value: 'String', label: 'String' },
    { value: 'Numeric', label: 'Numeric' },
    { value: 'Boolean', label: 'Boolean' },
    { value: 'DateTime', label: 'DateTime' },
    { value: 'Object', label: 'Object' },
]

function getErrorMessage(error: any, defaultMessage: string): string {
    // Handle field-specific errors from DRF serializer
    if (error.name) {
        return error.name
    }
    if (error.properties) {
        return error.properties
    }

    // Handle detail string errors
    if (error.detail) {
        const detail = error.detail

        // Handle duplicate property name constraint
        if (typeof detail === 'string' && detail.includes('unique_property_group_property_name')) {
            const nameMatch = detail.match(/\(property_group_id, name\)=\([^,]+, ([^)]+)\)/)
            if (nameMatch) {
                return `A property named "${nameMatch[1]}" already exists in this group`
            }
            return 'A property with this name already exists in this group'
        }

        // Handle duplicate property group name constraint
        if (typeof detail === 'string' && detail.includes('unique_property_group_name')) {
            const nameMatch = detail.match(/\(team_id, name\)=\([^,]+, ([^)]+)\)/)
            if (nameMatch) {
                return `A property group named "${nameMatch[1]}" already exists`
            }
            return 'A property group with this name already exists'
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

export interface SchemaPropertyGroupProperty {
    id: string
    name: string
    property_type: PropertyType
    is_required: boolean
    description: string
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

export interface PropertyGroupFormType {
    name: string
    description: string
    properties: SchemaPropertyGroupProperty[]
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
        addPropertyToForm: true,
        updatePropertyInForm: (index: number, updates: Partial<SchemaPropertyGroupProperty>) => ({ index, updates }),
        removePropertyFromForm: (index: number) => ({ index }),
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
                    } catch (error: any) {
                        const errorMessage = getErrorMessage(error, 'Failed to create property group')
                        lemonToast.error(errorMessage)
                        throw new Error(errorMessage)
                    }
                },
                updatePropertyGroup: async ({ id, data }: { id: string; data: Partial<SchemaPropertyGroup> }) => {
                    try {
                        const response = await api.update(`api/projects/@current/schema_property_groups/${id}/`, data)
                        lemonToast.success('Property group updated')
                        return values.propertyGroups.map((pg) => (pg.id === id ? response : pg))
                    } catch (error: any) {
                        const errorMessage = getErrorMessage(error, 'Failed to update property group')
                        lemonToast.error(errorMessage)
                        throw new Error(errorMessage)
                    }
                },
            },
        ],
    })),
    forms(({ actions, values }) => ({
        propertyGroupForm: {
            options: { showErrorsOnTouch: true },
            defaults: { name: '', description: '', properties: [] } as PropertyGroupFormType,
            errors: ({ name }) => ({
                name: !name?.trim() ? 'Property group name is required' : undefined,
            }),
            submit: async (formValues) => {
                // Check for validation errors
                const validationError = values.propertyGroupFormValidationError
                if (validationError) {
                    lemonToast.error(validationError)
                    throw new Error(validationError)
                }

                const data = {
                    name: formValues.name,
                    description: formValues.description,
                    properties: formValues.properties.map((p) => ({ ...p, name: p.name.trim() })),
                }

                try {
                    if (values.editingPropertyGroup) {
                        await actions.updatePropertyGroup({ id: values.editingPropertyGroup.id, data })
                    } else {
                        await actions.createPropertyGroup(data)
                    }
                    actions.setPropertyGroupModalOpen(false)
                } catch (error) {
                    // Error is already handled by the loaders
                    throw error
                }
            },
        },
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
        propertyGroupForm: [
            { name: '', description: '', properties: [] } as PropertyGroupFormType,
            {
                addPropertyToForm: (state) => ({
                    ...state,
                    properties: [
                        ...state.properties,
                        {
                            id: `new-${Date.now()}`,
                            name: '',
                            property_type: 'String' as PropertyType,
                            is_required: false,
                            description: '',
                        },
                    ],
                }),
                updatePropertyInForm: (state, { index, updates }) => ({
                    ...state,
                    properties: state.properties.map((prop, i) => (i === index ? { ...prop, ...updates } : prop)),
                }),
                removePropertyFromForm: (state, { index }) => ({
                    ...state,
                    properties: state.properties.filter((_, i) => i !== index),
                }),
                setEditingPropertyGroup: (_, { propertyGroup }) => ({
                    name: propertyGroup?.name || '',
                    description: propertyGroup?.description || '',
                    properties: propertyGroup?.properties || [],
                }),
                setPropertyGroupModalOpen: (state, { open }) =>
                    open ? state : { name: '', description: '', properties: [] },
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
        propertyGroupFormValidationError: [
            (s) => [s.propertyGroupForm],
            (form): string | null => {
                if (form.properties.length === 0) {
                    return null
                }

                const emptyProperties = form.properties.filter((prop) => !prop.name || !prop.name.trim())
                if (emptyProperties.length > 0) {
                    return 'All properties must have a name'
                }

                const invalidProperties = form.properties.filter(
                    (prop) => prop.name && prop.name.trim() && !/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(prop.name.trim())
                )
                if (invalidProperties.length > 0) {
                    return 'Property names must start with a letter or underscore and contain only letters, numbers, and underscores'
                }

                return null
            },
        ],
    }),
    listeners(({ actions }) => ({
        deletePropertyGroup: async ({ id }) => {
            try {
                await api.delete(`api/projects/@current/schema_property_groups/${id}/`)
                actions.loadPropertyGroups()
                lemonToast.success('Property group deleted')
            } catch (error: any) {
                const errorMessage = getErrorMessage(error, 'Failed to delete property group')
                lemonToast.error(errorMessage)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPropertyGroups()
    }),
])
