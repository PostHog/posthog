import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { EventOrPropType } from './VolumeTable'
import { definitionDrawerLogicType } from './definitionDrawerLogicType'
import React from 'react'
import { eventDefinitionsLogic } from './eventDefinitionsLogic'
import { ViewType } from 'scenes/insights/insightLogic'
import { IndexedTrendResult } from 'scenes/trends/trendsLogic'
import { toParams } from 'lib/utils'
import { EventFormattedType, TrendResult } from '~/types'

export const definitionDrawerLogic = kea<definitionDrawerLogicType>({
    actions: () => ({
        openDefinitionDrawer: (type: string, id: string) => ({ type, id }),
        setType: (type: string) => ({ type }),
        setDefinition: (definition: EventOrPropType) => ({ definition }),
        closeDrawer: () => false,
        updateDefinition: (payload: Partial<EventOrPropType>) => ({ payload }),
        saveNewTag: (tag: string) => ({ tag }),
        deleteTag: (tag: string) => ({ tag }),
        setDefinitionLoading: (loading: boolean) => ({ loading }),
        changeOwner: (ownerId: number) => ({ ownerId }),
        setDescription: (description: string) => ({ description }),
        setDescriptionEditing: (editing: boolean) => ({ editing }),
        setGraphResults: (results: any) => ({ results }),
        setVisibilityById: (entry: Record<number, boolean>) => ({ entry }),
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
        eventsSnippet: [],
        graphResults: [
            [] as IndexedTrendResult[],
            {
                setGraphResults: (_, { results }) => results,
            },
        ],
        visibilityMap: [
            {} as Record<number, any>,
            {
                setVisibilityById: (state: Record<number, any>, { entry }: { entry: Record<number, any> }) => ({
                    ...state,
                    ...entry,
                }),
            },
        ],
    }),
    loaders: () => ({
        eventsSnippet: [
            [] as EventFormattedType[],
            {
                loadEventsSnippet: async (definition: EventOrPropType) => {
                    const urlParams = toParams({
                        properties: {},
                        ...{ event: definition.name },
                        orderBy: ['-timestamp'],
                    })
                    const events = await api.get(`api/event/?${urlParams}`)
                    return events.results.slice(0, 3)
                },
            },
        ],
    }),
    // loaders: ({ actions }) => ({
    //     graphResults: [
    //         [] as IndexedTrendResult[],
    //         {
    //             loadGraphResults: async (definition) => {
    //                 const params = {
    //                     insight: ViewType.TRENDS,
    //                     interval: 'day',
    //                     display: 'ActionsLineGraph',
    //                     actions: [],
    //                     events: [
    //                         {
    //                             id: definition.name,
    //                             name: definition.name,
    //                             type: 'events',
    //                             order: 0,
    //                             properties: [],
    //                         },
    //                     ],
    //                 }
    //                 const result = (await api.get('api/insight/trend/?' + toParams(params))).result as TrendResult[]
    //                 console.log('RESULT', result)
    //                 return result
    //                 // return results.map((element, index) => {
    //                 //     actions.setVisibilityById({ [`${index}`]: true })
    //                 //     return { ...element, id: index }
    //                 // })
    //             },
    //             setVisibilityById: (state: Record<number, any>, { entry }: { entry: Record<number, any> }) => ({
    //                 ...state,
    //                 ...entry,
    //             }),
    //         },
    //     ]
    // }),
    listeners: ({ actions, values }) => ({
        openDefinitionDrawer: async ({ type, id }) => {
            const definitionType = type === 'event' ? 'event_definitions' : 'property_definitions'
            actions.setType(definitionType)
            const response = await api.get(`api/projects/@current/${definitionType}/${id}`)
            actions.setDefinition(response)
            actions.setDescription(response.description)
            actions.loadEventsSnippet(response)
            if (type === 'event') {
                const params = {
                    insight: ViewType.TRENDS,
                    interval: 'day',
                    display: 'ActionsLineGraph',
                    actions: [],
                    events: [
                        {
                            id: response.name,
                            name: response.name,
                            type: 'events',
                            order: 0,
                            properties: [],
                        },
                    ],
                }
                const results = (await api.get('api/insight/trend/?' + toParams(params))).result as TrendResult[]
                const indexedResults = results.map((element, index) => {
                    actions.setVisibilityById({ [`${index}`]: true })
                    return { ...element, id: index }
                })
                actions.setGraphResults(indexedResults)
            }
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
            actions.setDescriptionEditing(false)
            actions.updateDefinition({ description: values.description })
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
