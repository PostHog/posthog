import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import {
    accountRelationshipDefinitionsCreate,
    accountRelationshipDefinitionsDestroy,
    accountRelationshipDefinitionsList,
    accountRelationshipDefinitionsPartialUpdate,
} from 'products/customer_analytics/frontend/generated/api'
import type { AccountRelationshipDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { relationshipDefinitionsLogicType } from './relationshipDefinitionsLogicType'

export interface RelationshipDefinitionFormValues {
    name: string
    description: string
}

const DEFAULT_FORM_VALUES: RelationshipDefinitionFormValues = {
    name: '',
    description: '',
}

// Cardinality is not exposed in the UI for now — every relationship is single-holder
// (the API default), though the schema already supports multi-holder definitions.
const serializeDefinition = ({
    name,
    description,
}: RelationshipDefinitionFormValues): {
    name: string
    description: string | null
} => ({
    name: name.trim(),
    description: description?.trim() || null,
})

const handleNameConflict = (error: unknown, setManualErrors: (errors: { name: string }) => void): boolean => {
    if ((error as { status?: number })?.status !== 409) {
        return false
    }
    setManualErrors({ name: 'A relationship with this name already exists.' })
    return true
}

export const relationshipDefinitionsLogic = kea<relationshipDefinitionsLogicType>([
    path([
        'products',
        'customer_analytics',
        'frontend',
        'scenes',
        'CustomerAnalyticsConfigurationScene',
        'account',
        'relationshipDefinitionsLogic',
    ]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        openCreateModal: true,
        openEditModal: (definition: AccountRelationshipDefinitionApi) => ({ definition }),
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
            null as AccountRelationshipDefinitionApi | null,
            {
                openCreateModal: () => null,
                openEditModal: (_, { definition }) => definition,
                closeModal: () => null,
            },
        ],
    }),
    loaders(({ values }) => ({
        definitions: [
            [] as AccountRelationshipDefinitionApi[],
            {
                loadDefinitions: async (): Promise<AccountRelationshipDefinitionApi[]> => {
                    const response = await accountRelationshipDefinitionsList(String(values.currentProjectId))
                    return response.results
                },
                deleteDefinition: async ({ id }: { id: string }): Promise<AccountRelationshipDefinitionApi[]> => {
                    await accountRelationshipDefinitionsDestroy(String(values.currentProjectId), id)
                    return values.definitions.filter((definition) => definition.id !== id)
                },
            },
        ],
    })),
    forms(({ values }) => ({
        relationshipDefinitionForm: {
            defaults: DEFAULT_FORM_VALUES,
            errors: ({ name }: RelationshipDefinitionFormValues) => ({
                name: !name?.trim() ? 'Name is required' : undefined,
            }),
            submit: async (formValues: RelationshipDefinitionFormValues) => {
                const projectId = String(values.currentProjectId)
                const body = serializeDefinition(formValues)
                if (values.editingDefinition) {
                    await accountRelationshipDefinitionsPartialUpdate(projectId, values.editingDefinition.id, body)
                } else {
                    await accountRelationshipDefinitionsCreate(projectId, body)
                }
            },
        },
    })),
    listeners(({ actions }) => ({
        openCreateModal: () => {
            actions.resetRelationshipDefinitionForm()
        },
        openEditModal: ({ definition }) => {
            actions.setRelationshipDefinitionFormValues({
                name: definition.name,
                description: definition.description ?? '',
            })
        },
        submitRelationshipDefinitionFormSuccess: () => {
            lemonToast.success('Relationship saved')
            actions.loadDefinitions()
            actions.closeModal()
        },
        submitRelationshipDefinitionFormFailure: ({ error }) => {
            // A name conflict is expected validation feedback, not an exception worth capturing.
            if (handleNameConflict(error, actions.setRelationshipDefinitionFormManualErrors)) {
                return
            }
            posthog.captureException(error, { scope: 'relationshipDefinitionsLogic.submit' })
            lemonToast.error('Failed to save relationship')
        },
        deleteDefinitionSuccess: () => {
            lemonToast.success('Relationship deleted')
        },
        deleteDefinitionFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'relationshipDefinitionsLogic.delete' })
            lemonToast.error('Failed to delete relationship')
        },
        loadDefinitionsFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'relationshipDefinitionsLogic.load' })
            lemonToast.error('Failed to load relationships')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDefinitions()
    }),
])
