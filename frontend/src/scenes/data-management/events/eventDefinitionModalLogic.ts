import { actions, kea, key, listeners, path, props, reducers } from 'kea'
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
    actions({
        setEventDefinitionFormValue: (key: keyof EventDefinitionFormType, value: any) => ({ key, value }),
    }),
    forms(() => ({
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

                const response = await api.eventDefinitions.create(payload)
                return response
            },
        },
    })),
    listeners(({ props }) => ({
        submitEventDefinitionFormSuccess: ({ eventDefinitionForm }) => {
            lemonToast.success(`Event "${eventDefinitionForm.name}" created successfully`)
            props.onClose()
            props.onSuccess?.()
        },
        submitEventDefinitionFormFailure: ({ error }) => {
            const errorMessage = error?.detail || error?.message || 'Failed to create event definition'
            lemonToast.error(errorMessage)
        },
    })),
    reducers({
        eventDefinitionForm: [
            {
                name: '',
                description: '',
                owner: null,
                tags: [],
            } as EventDefinitionFormType,
            {
                setEventDefinitionFormValue: (state, { key, value }) => ({
                    ...state,
                    [key]: value,
                }),
            },
        ],
    }),
])
