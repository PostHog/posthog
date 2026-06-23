import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import {
    customPropertyDefinitionsCreate,
    customPropertyDefinitionsDestroy,
    customPropertyDefinitionsList,
    customPropertyDefinitionsPartialUpdate,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    CustomPropertyDefinitionApi,
    CustomPropertyDisplayTypeEnumApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import type { customPropertyDefinitionsLogicType } from './customPropertyDefinitionsLogicType'
import { isNumericDisplayType } from './customPropertyTypes'

export interface CustomPropertyFormValues {
    name: string
    description: string
    displayType: CustomPropertyDisplayTypeEnumApi
    isBigNumber: boolean
}

const DEFAULT_FORM_VALUES: CustomPropertyFormValues = {
    name: '',
    description: '',
    displayType: 'text',
    isBigNumber: false,
}

export const customPropertyDefinitionsLogic = kea<customPropertyDefinitionsLogicType>([
    path([
        'products',
        'customer_analytics',
        'frontend',
        'scenes',
        'CustomerAnalyticsConfigurationScene',
        'account',
        'customPropertyDefinitionsLogic',
    ]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        openCreateModal: true,
        openEditModal: (definition: CustomPropertyDefinitionApi) => ({ definition }),
        closeModal: true,
    }),
    reducers({
        modalVisible: [
            false,
            {
                openCreateModal: () => true,
                openEditModal: () => true,
                closeModal: () => false,
            },
        ],
        editingDefinition: [
            null as CustomPropertyDefinitionApi | null,
            {
                openCreateModal: () => null,
                openEditModal: (_, { definition }) => definition,
                closeModal: () => null,
            },
        ],
    }),
    loaders(({ values }) => ({
        definitions: [
            [] as CustomPropertyDefinitionApi[],
            {
                loadDefinitions: async (): Promise<CustomPropertyDefinitionApi[]> => {
                    const response = await customPropertyDefinitionsList(String(values.currentProjectId))
                    return response.results
                },
                deleteDefinition: async ({ id }: { id: string }): Promise<CustomPropertyDefinitionApi[]> => {
                    await customPropertyDefinitionsDestroy(String(values.currentProjectId), id)
                    return values.definitions.filter((definition) => definition.id !== id)
                },
            },
        ],
    })),
    forms(({ values }) => ({
        customPropertyForm: {
            defaults: DEFAULT_FORM_VALUES,
            errors: ({ name }: CustomPropertyFormValues) => ({
                name: !name?.trim() ? 'Name is required' : undefined,
            }),
            submit: async ({ name, description, displayType, isBigNumber }: CustomPropertyFormValues) => {
                const body = {
                    name: name.trim(),
                    description: description?.trim() || null,
                    display_type: displayType,
                    // The switch is hidden for non-numeric types, so never send a stale flag for them.
                    is_big_number: isNumericDisplayType(displayType) ? isBigNumber : false,
                }
                const editing = values.editingDefinition
                if (editing) {
                    await customPropertyDefinitionsPartialUpdate(String(values.currentProjectId), editing.id, body)
                } else {
                    await customPropertyDefinitionsCreate(String(values.currentProjectId), body)
                }
            },
        },
    })),
    listeners(({ actions, values }) => ({
        openCreateModal: () => {
            actions.resetCustomPropertyForm()
        },
        openEditModal: ({ definition }) => {
            actions.setCustomPropertyFormValues({
                name: definition.name,
                description: definition.description ?? '',
                displayType: definition.display_type,
                isBigNumber: definition.is_big_number ?? false,
            })
        },
        submitCustomPropertyFormSuccess: () => {
            lemonToast.success(values.editingDefinition ? 'Custom property updated' : 'Custom property created')
            actions.loadDefinitions()
            actions.closeModal()
        },
        submitCustomPropertyFormFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.submit' })
            if ((error as { status?: number })?.status === 409) {
                actions.setCustomPropertyFormManualErrors({
                    name: 'A custom property with this name already exists.',
                })
                return
            }
            lemonToast.error('Failed to save custom property')
        },
        deleteDefinitionSuccess: () => {
            lemonToast.success('Custom property deleted')
        },
        deleteDefinitionFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.delete' })
            lemonToast.error('Failed to delete custom property')
        },
        loadDefinitionsFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.load' })
            lemonToast.error('Failed to load custom properties')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDefinitions()
    }),
])
