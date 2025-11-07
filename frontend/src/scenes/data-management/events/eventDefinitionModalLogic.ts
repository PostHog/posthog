import { kea, key, path, props } from 'kea'
import { forms } from 'kea-forms'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { EventDefinition } from '~/types'

import type { eventDefinitionModalLogicType } from './eventDefinitionModalLogicType'

export interface EventDefinitionModalLogicProps {
    onSuccess?: () => void
    onClose: () => void
}

export interface EventDefinitionFormType {
    name: string
    description?: string
    owner?: number | null
    tags?: string[]
}

export const eventDefinitionModalLogic = kea<eventDefinitionModalLogicType>([
    path(['scenes', 'data-management', 'events', 'eventDefinitionModalLogic']),
    props({} as EventDefinitionModalLogicProps),
    key((props) => props.onSuccess?.toString() || 'default'),
    forms(({ props }) => ({
        eventDefinitionForm: {
            defaults: {
                name: '',
                description: '',
                owner: null,
                tags: [],
            } as EventDefinitionFormType,
            errors: ({ name }) => ({
                name: !name ? 'Event name is required' : undefined,
            }),
            submit: async (formValues) => {
                try {
                    const payload: Partial<EventDefinition> = {
                        name: formValues.name.trim(),
                    }

                    if (formValues.description) {
                        payload.description = formValues.description
                    }
                    if (formValues.owner) {
                        payload.owner = { id: formValues.owner } as any
                    }
                    if (formValues.tags && formValues.tags.length > 0) {
                        payload.tags = formValues.tags
                    }

                    await api.eventDefinitions.create(payload)

                    lemonToast.success(`Event "${formValues.name}" created successfully`)
                    props.onClose()
                    props.onSuccess?.()
                } catch (error: any) {
                    const errorMessage = error?.detail || error?.message || 'Failed to create event definition'
                    lemonToast.error(errorMessage)
                    throw error
                }
            },
        },
    })),
])
