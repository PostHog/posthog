import { actions, kea, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { EventDefinition } from '~/types'

import type { eventDefinitionModalLogicType } from './eventDefinitionModalLogicType'

export interface EventDefinitionModalLogicProps {
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
    actions({
        checkEventNameExists: (name: string) => ({ name }),
    }),
    loaders(() => ({
        existingEvent: [
            null as EventDefinition | null,
            {
                checkEventNameExists: async ({ name }, breakpoint) => {
                    if (!name || name.trim().length === 0) {
                        return null
                    }
                    await breakpoint(300)
                    try {
                        const response = await api.eventDefinitions.list({
                            search: name.trim(),
                        })
                        breakpoint()
                        // Find exact match
                        const exactMatch = response.results?.find((e: EventDefinition) => e.name === name.trim())
                        return exactMatch || null
                    } catch {
                        return null
                    }
                },
            },
        ],
    })),
    reducers({
        existingEvent: {
            resetEventDefinitionForm: () => null,
        },
    }),
    forms(({ props, actions, values }) => ({
        eventDefinitionForm: {
            defaults: {
                name: '',
                description: '',
                owner: null,
                tags: [],
            } as EventDefinitionFormType,
            errors: ({ name }) => ({
                name: !name
                    ? 'Event name is required'
                    : values.existingEvent
                      ? `Event "${name}" already exists`
                      : undefined,
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
                        payload.owner = formValues.owner as any
                    }
                    if (formValues.tags && formValues.tags.length > 0) {
                        payload.tags = formValues.tags
                    }

                    const createdEvent = await api.eventDefinitions.create(payload)

                    lemonToast.success(`Event "${formValues.name}" created successfully`)
                    actions.resetEventDefinitionForm()
                    props.onClose()
                    router.actions.push(urls.eventDefinition(createdEvent.id))
                } catch (error: any) {
                    const errorMessage = error?.detail || error?.message || 'Failed to create event definition'
                    lemonToast.error(errorMessage)
                    throw error
                }
            },
        },
    })),
    listeners(({ actions }) => ({
        setEventDefinitionFormValue: ({ name, value }) => {
            if (name === 'name' && typeof value === 'string') {
                actions.checkEventNameExists(value)
            }
        },
    })),
])
