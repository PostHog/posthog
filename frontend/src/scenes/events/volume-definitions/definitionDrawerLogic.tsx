import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { EventOrPropType } from './VolumeTable'
import { definitionDrawerLogicType } from './definitionDrawerLogicType'
import React from 'react'
import { eventDefinitionsLogic } from './eventDefinitionsLogic'

export const definitionDrawerLogic = kea<definitionDrawerLogicType>({
    actions: () => ({
        openDefinitionDrawer: (type: string, id: string) => ({ type, id }),
        setType: (type: string) => ({ type }),
        setDefinition: (definition: EventOrPropType) => ({ definition }),
        closeDrawer: () => false,
        updateDefinition: (payload: Partial<EventOrPropType>) => ({ payload }),
        saveNewTag: (tag) => ({ tag }),
        deleteTag: (tag) => ({ tag }),
        setDefinitionLoading: (loading) => ({ loading }),
        changeOwner: (ownerId: number) => ({ ownerId }),
        setDescription: (description: string) => ({ description }),
        setDescriptionEditing: (editing: boolean) => ({ editing }),
        cancelDescription: true,
        saveDescription: true,
    }),
    reducers: () => ({
        drawerState: [
            false,
            {
                openDefinitionDrawer: () => true,
                closeDrawer: () => false,
            },
        ],
        definition: [
            null as EventOrPropType | null,
            {
                setDefinition: (_, { definition }) => definition,
            },
        ],
        description: [
            '',
            {
                setDescription: (_, { description }) => description,
            },
        ],
        type: [
            '',
            {
                setType: (_, { type }) => type,
            },
        ],
        editing: [
            false,
            {
                setDescriptionEditing: (_, { editing }) => editing,
            },
        ],
        definitionLoading: [
            false,
            {
                setDefinitionLoading: (_, { loading }) => loading,
            },
        ],
    }),
    selectors: () => ({}),
    listeners: ({ actions, values }) => ({
        openDefinitionDrawer: async ({ type, id }) => {
            const definitionType = type === 'event' ? 'event_definitions' : 'property_definitions'
            actions.setType(definitionType)
            const response = await api.get(`api/projects/@current/${definitionType}/${id}`)
            actions.setDefinition(response)
            actions.setDescription(response.description)
        },
        saveNewTag: ({ tag }) => {
            if (values.definition.tags.includes(tag)) {
                toast.error(
                    // TODO: move to errorToast once #3561 is merged
                    <div>
                        <h1>Oops! Can't add that tag</h1>
                        <p>Your event already has that tag.</p>
                    </div>
                )
                return
            }
            actions.updateDefinition({ tags: [...values.definition.tags, tag] })
        },
        deleteTag: async ({ tag }, breakpoint) => {
            await breakpoint(100)
            const tags = values.definition.tags.filter((_tag: string) => _tag !== tag)
            actions.updateDefinition({ tags })
        },
        changeOwner: ({ ownerId }) => {
            actions.updateDefinition({ owner_id: ownerId })
        },
        cancelDescription: () => {
            actions.setDescription(values.definition.description)
            actions.setDescriptionEditing(false)
        },
        saveDescription: () => {
            actions.updateDefinition({ description: values.description })
            actions.setDescriptionEditing(false)
        },
        updateDefinition: async ({ payload }) => {
            actions.setDefinitionLoading(true)
            const response = await api.update(`api/projects/@current/${values.type}/${values.definition.id}/`, payload)
            actions.setDefinition(response)
            actions.setDefinitionLoading(false)
            eventDefinitionsLogic.actions.setEventDefinitions(response)
        },
    }),
})
