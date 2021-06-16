import { kea } from 'kea'
import api from 'lib/api'
import { definitionDrawerLogicType } from './definitionDrawerLogicType'
import { IndexedTrendResult } from 'scenes/trends/trendsLogic'
import { EventDefinition, EventOrPropType, EventType, PropertyDefinition, UserBasicType } from '~/types'
import { errorToast, toParams, uniqueBy } from 'lib/utils'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

export const definitionDrawerLogic = kea<
    definitionDrawerLogicType<
        EventOrPropType,
        EventDefinition,
        PropertyDefinition,
        EventType,
        UserBasicType,
        IndexedTrendResult
    >
>({
    actions: () => ({
        openDrawer: (type: string, id: string) => ({ type, id }),
        setDrawerType: (type: string) => ({ type }),
        setDescription: (description: string | undefined) => ({ description }),
        setNewTag: (tag: string) => ({ tag }),
        deleteTag: (tag: string) => ({ tag }),
        changeOwner: (owner: UserBasicType) => ({ owner }),
        setDefinition: (definition: Partial<EventOrPropType>) => ({ definition }),
        setNewEventPropertyTag: (tag: string, currentTags?: string[], id?: string) => ({ tag, currentTags, id }),
        deleteEventPropertyTag: (tag: string, currentTags?: string[], id?: string) => ({ tag, currentTags, id }),
        setEventPropertyDescription: (description: string, id: string) => ({ description, id }),
        setEventPropertyDefinition: (propertyDefinition: Partial<PropertyDefinition>, id: string | undefined) => ({
            propertyDefinition,
            id,
        }),
        setEventPropertyDefinitionUpdateList: (id: string | undefined) => ({ id }),
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
                    const saved = await api.update(
                        `api/projects/@current/${type}_definitions/${definition.id}`,
                        definition
                    )
                    if (type === 'event') {
                        eventDefinitionsModel.actions.setEventDefinitions(saved)
                    }
                    return saved
                },
            },
        ],
        eventsSnippet: [
            [] as EventType[],
            {
                loadEventsSnippet: async (definition: EventOrPropType | null) => {
                    const eventsParams = toParams({
                        properties: {},
                        ...{ event: definition?.name },
                        orderBy: ['-timestamp'],
                        limit: 5,
                    })
                    const events = await api.get(`api/event/?${eventsParams}`)
                    actions.loadEventsSnippetSuccess(events.results)
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
                    return { ...state, ...definition }
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
                    const newDefinitions = [] as PropertyDefinition[]
                    state.forEach((propertyDef) => newDefinitions.push(Object.assign({}, propertyDef)))
                    const propertyToChange = newDefinitions.findIndex((def) => def.id === id)
                    newDefinitions[propertyToChange] = { ...newDefinitions[propertyToChange], ...propertyDefinition }
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
    selectors: () => ({
        eventDefinitionTags: [
            () => [eventDefinitionsModel.selectors.eventDefinitions],
            (definitions: EventDefinition[]): string[] => {
                const allTags = definitions.flatMap(({ tags }) => tags).filter((a) => !!a) as string[]
                return uniqueBy(allTags, (item) => item).sort()
            },
        ],
        eventPropertiesDefinitionTags: [
            (selectors) => [selectors.eventPropertiesDefinitions],
            (properties: PropertyDefinition[]): string[] => {
                const allTags = properties.flatMap(({ tags }) => tags).filter((a) => !!a) as string[]
                return uniqueBy(allTags, (item) => item).sort()
            },
        ],
        propertyDefinitionTags: [
            () => [propertyDefinitionsModel.selectors.propertyDefinitions],
            (definitions: EventOrPropType[]): string[] => {
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
            actions.setDescription(definition?.description)
        },
        loadEventsSnippetSuccess: ({ eventsSnippet }) => {
            const propertyNames = Object.keys(eventsSnippet[0].properties).filter((key) => !keyMapping.event[key])
            actions.loadEventPropertiesDefinitions(propertyNames)
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
