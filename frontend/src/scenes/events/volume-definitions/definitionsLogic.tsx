
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { definitionsLogicType } from './definitionsLogicType'
import { EventOrPropType } from './VolumeTable'
import React from 'react'

export const definitionsLogic = kea<definitionsLogicType>({
    actions: () => ({
        openDefinitionDrawer: (type: string, id: string) => ({ type, id }),
        setDefinition: (definition: EventOrPropType) => ({ definition }),
        closeDrawer: () => false,
        saveNewTag: (tag) => ({ tag }),
        deleteTag: (tag) => ({ tag }),
        updateDefinition: (payload: Partial<EventOrPropType>) => ({ payload }),
        setType: (type: string) => ({ type }),
        setDefinitionLoading: (loading) => ({ loading })
    }),
    reducers: ({ values }) => ({
        drawerState: [
            false,
            {
                openDefinitionDrawer: () => true,
                closeDrawer: () => false
            },
        ],
        definition: [
            null as EventOrPropType | null,
            {
                setDefinition: (_, { definition }) => definition,
            }
        ],
        type: [
            {},
            {
                setType: (_, { type }) => {
                    // debugger
                    return type
                }
            }
        ],
        definitionLoading: [
            false,
            {
                setDefinitionLoading: (_, { loading }) => loading,
            }
        ]
    }),
    selectors: () => ({
        tags: [
            (selectors) => [selectors.definition],
            (definition: EventOrPropType) => {
                return definition?.tags
            }
        ],
        definitionType: [
            (selectors) => [selectors.definition]
        ]
    }),
    listeners: ({ actions, values }) => ({
        openDefinitionDrawer: async ({ type, id }) => {
            const definitionType = type === 'event' ? 'event_definitions' : 'property_definitions'
            actions.setType(definitionType)
            const response = await api.get(`api/projects/@current/${definitionType}/${id}`)
            actions.setDefinition(response)
        },
        saveNewTag: ({ tag }) => {
            if (values.tags.includes(tag)) {
                toast.error(
                    // TODO: move to errorToast once #3561 is merged
                    <div>
                        <h1>Oops! Can't add that tag</h1>
                        <p>Your event already has that tag.</p>
                    </div>
                )
                return
            }
            actions.updateDefinition({ tags: [...values.tags, tag] })
        },
        deleteTag: async ({ tag }, breakpoint) => {
            await breakpoint(100)
            const tags = values.tags.filter((_tag) => _tag !== tag)
            actions.updateDefinition({ tags })
        },

        // deleteTag: async ({ tag }, breakpoint) => {
        //     await breakpoint(100)
        //     actions.triggerDashboardUpdate({ tags: values.tags.filter((_tag) => _tag !== tag) })
        // },
        updateDefinition: async ({ payload }) => {
            console.log(values.type)
            // const definitionType = payload.owner === 'event' ? 'event_definitions' : 'property_definitions'
            // debugger
            actions.setDefinitionLoading(true)
            const response = await api.update(`api/projects/@current/${values.type}/${values.definition.id}/`, payload)
            actions.setDefinition(response)
            actions.setDefinitionLoading(false)
        }
    })
})