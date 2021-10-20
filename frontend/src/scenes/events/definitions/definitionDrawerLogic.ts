import { kea } from 'kea'
import api from 'lib/api'
import { definitionDrawerLogicType } from './definitionDrawerLogicType'
import { IndexedTrendResult } from 'scenes/trends/types'
import { EventDefinition, EventOrPropType, EventType, PropertyDefinition, UserBasicType } from '~/types'
import { errorToast, toParams, uniqueBy } from 'lib/utils'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { teamLogic } from '../../teamLogic'

export const definitionDrawerLogic = kea<definitionDrawerLogicType>({
    actions: () => ({
        openDrawer: (type: string, id: string) => ({ type, id }),
        setDrawerType: (type: string) => ({ type }),
        setDescription: (description: string) => ({ description }),
        setNewTag: (tag: string) => ({ tag }),
        deleteTag: (tag: string) => ({ tag }),
        changeOwner: (owner: UserBasicType) => ({ owner }),
        setDefinition: (definition: Partial<EventOrPropType>) => ({ definition }),
        setNewEventPropertyTag: (tag: string, currentTags?: string[], id?: string) => ({ tag, currentTags, id }),
        deleteEventPropertyTag: (tag: string, currentTags?: string[], id?: string) => ({ tag, currentTags, id }),
        setEventPropertyDescription: (description: string, id: string) => ({ description, id }),
        setEventPropertyDefinition: (propertyDefinition: Partial<PropertyDefinition>, id?: string) => ({
            propertyDefinition,
            id,
        }),
        setEventPropertyDefinitionUpdateList: (id?: string) => ({ id }),
        closeDrawer: true,
        setTagLoading: (loading: boolean) => ({ loading }),
        saveAll: true,
        setGraphResults: (results: any) => ({ results }),
        setVisibilityById: (entry: Record<number, boolean>) => ({ entry }),
    }),
    loaders: ({ actions, values }) => ({
        definition: [
            null as EventOrPropType | null,
            {
                loadDefinition: async ({ type, id }) => {
                    const definition = await api.get(`api/projects/@current/${type}_definitions/${id}`)
                    return definition
                },
                saveDefinition: async ({ definition, type }) => {
                    if (type === 'event') {
                        definition.owner = definition.owner.user?.id || null
                        definition.description = values.description
                    }
                    if (type === 'property' && values.type === 'property') {
                        definition.description = values.description
                    }
                    const updatedDefinition = await api.update(
                        `api/projects/@current/${type}_definitions/${definition.id}`,
                        definition
                    )
                    actions.saveDefinitionSuccess(updatedDefinition)
                    return updatedDefinition
                },
            },
        ],
        eventsSnippet: [
            [] as EventType[],
            {
                loadEventsSnippet: async (definition: EventOrPropType | null) => {
                    const properties =
                        values.type === 'property'
                            ? [{ key: definition?.name, value: 'is_set', operator: 'is_set', type: 'event' }]
                            : {}
                    const event = values.type === 'event' ? definition?.name : null
                    const eventsParams = toParams({
                        properties: properties,
                        ...{ event },
                        orderBy: ['-timestamp'],
                        limit: 5,
                    })
                    const events = await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/events/?${eventsParams}`
                    )
                    if (values.type === 'property') {
                        actions.loadEventsSnippetSuccess(events.results)
                    }
                    return events.results
                },
            },
        ],
        eventPropertiesDefinitions: [
            [] as PropertyDefinition[],
            {
                loadEventPropertiesDefinitions: async (propertyNames) => {
                    const propertyDefinitions = await api.get(
                        `api/projects/@current/property_definitions/?properties=${propertyNames}`
                    )
                    return propertyDefinitions.results
                },
            },
        ],
    }),
    reducers: () => ({
        drawerState: [
            false,
            {
                openDrawer: () => true,
                closeDrawer: () => false,
            },
        ],
        description: [
            '',
            {
                setDescription: (_, { description }) => description,
            },
        ],
        definition: [
            null as EventOrPropType | null,
            {
                setDefinition: (state, { definition }) => {
                    return { ...state, ...definition } as EventOrPropType
                },
            },
        ],
        tagLoading: [
            false,
            {
                setTagLoading: (_, { loading }) => loading,
            },
        ],
        type: [
            '',
            {
                setDrawerType: (_, { type }) => type,
            },
        ],
        eventPropertiesDefinitions: [
            [] as PropertyDefinition[],
            {
                setEventPropertyDefinition: (state, { propertyDefinition, id }) => {
                    const newDefinitions = state.map((p) => (p.id === id ? { ...p, ...propertyDefinition } : p))
                    return newDefinitions
                },
            },
        ],
        editedEventPropertyDefinitions: [
            [] as string[],
            {
                setEventPropertyDefinitionUpdateList: (state, { id }) => {
                    if (id && !state.includes(id)) {
                        return [...state, id]
                    }
                    return [...state]
                },
            },
        ],
        graphResults: [
            [] as IndexedTrendResult[],
            {
                setGraphResults: (_, { results }) => results,
            },
        ],
    }),
    selectors: () => ({
        eventDefinitionTags: [
            () => [eventDefinitionsModel.selectors.eventDefinitions],
            (definitions): string[] => {
                const allTags = definitions.flatMap(({ tags }) => tags).filter((a) => !!a) as string[]
                return uniqueBy(allTags, (item) => item).sort()
            },
        ],
        eventPropertiesDefinitionTags: [
            (selectors) => [selectors.eventPropertiesDefinitions],
            (properties): string[] => {
                const allTags = properties.flatMap(({ tags }) => tags).filter((a) => !!a) as string[]
                return uniqueBy(allTags, (item) => item).sort()
            },
        ],
        propertyDefinitionTags: [
            () => [propertyDefinitionsModel.selectors.propertyDefinitions],
            (definitions): string[] => {
                const allTags = definitions.flatMap(({ tags }) => tags).filter((a) => !!a) as string[]
                return uniqueBy(allTags, (item) => item).sort()
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        openDrawer: ({ type, id }) => {
            actions.setDrawerType(type)
            actions.loadDefinition({ type, id })
        },
        loadDefinitionSuccess: ({ definition }) => {
            actions.loadEventsSnippet(definition)
            actions.setDescription(definition?.description || '')
        },
        loadEventsSnippetSuccess: ({ eventsSnippet }) => {
            const propertyNames = Object.keys(eventsSnippet[0].properties).filter((key) => !keyMapping.event[key])
            actions.loadEventPropertiesDefinitions(propertyNames)
        },
        saveDefinitionSuccess: ({ definition }) => {
            if (values.type === 'event') {
                eventDefinitionsModel.actions.updateEventDefinition(definition as EventDefinition)
            } else {
                propertyDefinitionsModel.actions.updatePropertyDefinition(definition as PropertyDefinition)
            }
        },
        setNewTag: async ({ tag }, breakpoint) => {
            actions.setTagLoading(true)
            if (values.definition?.tags?.includes(tag)) {
                errorToast('Oops! This tag is already set', 'This event already includes the proposed tag.')
                return
            }
            const currentTags = values.definition?.tags ? [...values.definition.tags, tag] : [tag]
            actions.setDefinition({ tags: currentTags })
            await breakpoint(100)
            actions.setTagLoading(false)
        },
        deleteTag: async ({ tag }, breakpoint) => {
            await breakpoint(100)
            const tags = values.definition?.tags?.filter((_tag: string) => _tag !== tag) || []
            actions.setDefinition({ tags })
        },
        changeOwner: ({ owner }) => {
            actions.setDefinition({ owner })
        },
        setNewEventPropertyTag: async ({ tag, currentTags, id }, breakpoint) => {
            actions.setTagLoading(true)
            if (currentTags?.includes(tag)) {
                errorToast('Oops! This tag is already set', 'This event already includes the proposed tag.')
                return
            }
            const tags = currentTags ? [...currentTags, tag] : []
            await breakpoint(100)
            actions.setTagLoading(false)
            actions.setEventPropertyDefinitionUpdateList(id)
            actions.setEventPropertyDefinition({ tags }, id)
        },
        deleteEventPropertyTag: async ({ tag, currentTags, id }, breakpoint) => {
            await breakpoint(100)
            const tags = currentTags?.filter((_tag: string) => _tag !== tag)
            actions.setEventPropertyDefinitionUpdateList(id)
            actions.setEventPropertyDefinition({ tags }, id)
        },
        setEventPropertyDescription: ({ description, id }) => {
            actions.setEventPropertyDefinition({ description }, id)
            actions.setEventPropertyDefinitionUpdateList(id)
        },
        saveAll: () => {
            actions.saveDefinition({ definition: { ...values.definition }, type: values.type })
            values.editedEventPropertyDefinitions.forEach((id) => {
                const property = values.eventPropertiesDefinitions.find((prop) => prop.id === id)
                actions.saveDefinition({ definition: { ...property }, type: 'property' })
            })
            actions.closeDrawer()
        },
    }),
})
