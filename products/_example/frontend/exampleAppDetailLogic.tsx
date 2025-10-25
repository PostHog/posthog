import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { createMockPerson, deleteMockPerson, fetchMockPerson, updateMockPerson } from '../backend/mockStore'
import { ExampleAppMockPerson } from './ExampleAppScene'
import type { exampleAppDetailLogicType } from './exampleAppDetailLogicType'

export interface ExampleAppDetailLogicProps {
    id: string
    tabId: string
}

const getNewPerson = (): ExampleAppMockPerson => ({
    id: 'new',
    name: '',
    description: '',
    createdAt: '',
    updatedAt: '',
})

export const exampleAppDetailLogic = kea<exampleAppDetailLogicType>([
    path(['products', 'example', 'frontend', 'exampleAppDetailLogic']),
    props({} as ExampleAppDetailLogicProps),
    tabAwareScene(),

    actions({
        updateName: (name: string) => ({ name }),
        updateDescription: (description: string) => ({ description }),
        resetForm: true,
        savePerson: true,
        deletePerson: true,
    }),

    loaders(({ props }) => ({
        person: [
            null as ExampleAppMockPerson | null,
            {
                loadPerson: async () => {
                    if (props.id === 'new') {
                        await new Promise((resolve) => setTimeout(resolve, 300))
                        return getNewPerson()
                    }

                    const person = await fetchMockPerson(props.id)
                    if (!person) {
                        throw new Error(`Person with id ${props.id} not found`)
                    }
                    return person
                },
            },
        ],
    })),

    reducers(({ props }) => ({
        originalPerson: [
            null as ExampleAppMockPerson | null,
            {
                loadPersonSuccess: (_, { person }) => person,
                savePersonSuccess: (_, { person }) => person,
            },
        ],

        person: [
            null as ExampleAppMockPerson | null,
            {
                loadPersonSuccess: (_, { person }) => person,
                updateName: (state, { name }) => (state ? { ...state, name } : state),
                updateDescription: (state, { description }) => (state ? { ...state, description } : state),
                savePersonSuccess: (_, { person }) => person,
                resetForm: (state) => {
                    if (props.id === 'new') {
                        return getNewPerson()
                    }
                    return state
                },
            },
        ],
    })),

    selectors({
        isNewPerson: [(_, p) => [p.id], (id: string) => id === 'new'],

        isLoading: [(s) => [s.personLoading], (personLoading: boolean) => personLoading],

        hasChanges: [
            (s) => [s.person, s.originalPerson],
            (person: ExampleAppMockPerson | null, originalPerson: ExampleAppMockPerson | null): boolean => {
                if (!person || !originalPerson) {
                    return false
                }
                return person.name !== originalPerson.name || person.description !== originalPerson.description
            },
        ],

        canSave: [
            (s) => [s.person, s.hasChanges, s.personLoading, s.isNewPerson],
            (
                person: ExampleAppMockPerson | null,
                hasChanges: boolean,
                personLoading: boolean,
                isNewPerson: boolean
            ): boolean => {
                if (!person || personLoading) {
                    return false
                }
                if (isNewPerson) {
                    return person.name.trim().length > 0
                }
                return hasChanges
            },
        ],

        breadcrumbs: [
            (s) => [s.person, s.isNewPerson, s.isLoading],
            (person: ExampleAppMockPerson | null, isNewPerson: boolean, isLoading: boolean): Breadcrumb[] => [
                {
                    key: sceneConfigurations[Scene.ExampleApp].name || 'Example App',
                    name: sceneConfigurations[Scene.ExampleApp].name,
                    path: urls.exampleApp(),
                    iconType: sceneConfigurations[Scene.ExampleApp].iconType,
                },
                {
                    key: ['Example App', person?.id || 'new'],
                    name: isNewPerson ? 'New person' : person?.name || 'Loading...',
                    iconType: isLoading ? 'loading' : 'example_icon_type',
                },
            ],
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadPerson()
    }),

    listeners(({ actions, values, props }) => ({
        savePersonFailure: ({ error }: { error: string }) => {
            lemonToast.error(error)
        },

        savePerson: async () => {
            const { person } = values
            if (!person) {
                lemonToast.error('No person to save')
                return
            }

            try {
                let savedPerson: ExampleAppMockPerson

                if (props.id === 'new') {
                    if (!person.name.trim()) {
                        lemonToast.error('Name is required')
                        return
                    }

                    savedPerson = await createMockPerson({
                        name: person.name.trim(),
                        description: person.description?.trim() || '',
                    })

                    lemonToast.success('Person created successfully')
                    router.actions.replace(urls.exampleAppDetail(savedPerson.id))
                } else {
                    savedPerson = await updateMockPerson(props.id, {
                        name: person.name.trim(),
                        description: person.description?.trim(),
                    })

                    lemonToast.success('Person updated successfully')
                }

                actions.loadPersonSuccess(savedPerson)
            } catch (error) {
                console.error('Failed to save person:', error)
                const errorMessage = error instanceof Error ? error.message : 'Failed to save person'
                lemonToast.error(errorMessage)
            }
        },

        deletePerson: async () => {
            if (props.id === 'new') {
                lemonToast.error('Cannot delete a new person')
                return
            }

            try {
                await deleteMockPerson(props.id)
                lemonToast.success('Person deleted successfully')
                router.actions.replace(urls.exampleApp())
            } catch (error) {
                console.error('Failed to delete person:', error)
                const errorMessage = error instanceof Error ? error.message : 'Failed to delete person'
                lemonToast.error(errorMessage)
            }
        },

        resetForm: () => {
            if (props.id === 'new') {
                // For new persons, the resetForm reducer handles it
                return
            } else if (values.originalPerson) {
                actions.loadPersonSuccess(values.originalPerson)
            }
        },
    })),
])
