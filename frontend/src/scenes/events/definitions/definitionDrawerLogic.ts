import { kea } from 'kea'
import api from 'lib/api'
import { definitionDrawerLogicType } from './definitionDrawerLogicType'
import { IndexedTrendResult } from 'scenes/trends/trendsLogic'
import { EventDefinition, EventFormattedType, EventOrPropType, PropertyDefinition } from '~/types'
import { errorToast, toParams, uniqueBy } from 'lib/utils'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { valueType } from 'antd/lib/statistic/utils'
import { keyMapping } from 'lib/components/PropertyKeyInfo'

export const definitionDrawerLogic = kea<definitionDrawerLogicType<EventOrPropType>>({
    actions: () => ({
        openDrawer: (type: string, id: string) => ({ type, id }),
        setType: (type: string) => ({ type }),
        setDefinition: (definition: EventOrPropType) => ({ definition }),
        updateDefinition: (payload: Partial<EventOrPropType>, id?: string) => ({ payload, id }),
        saveNewTag: (tag: string) => ({ tag }),
        deleteTag: (tag: string) => ({ tag }),
        saveNewPropertyTag: (tag: string, currentTags?: string[], propertyId?: string) => ({
            tag,
            currentTags,
            propertyId,
        }),
        deletePropertyTag: (tag: string, currentTags?: string[], propertyId?: string) => ({
            tag,
            currentTags,
            propertyId,
        }),
        setDefinitionLoading: (loading: boolean) => ({ loading }),
        changeOwner: (ownerId: valueType) => ({ ownerId }),
        setDescription: (description: string) => ({ description }),
        setGraphResults: (results: any) => ({ results }),
        setPropertyDescription: (description: string, id: string) => ({ description, id }),
        setVisibilityById: (entry: Record<number, boolean>) => ({ entry }),
        setSaveAllLoading: (loading: boolean) => ({ loading }),
        updateAllDescriptions: true,
        closeDrawer: true,
    }),
    loaders: ({ actions, values }) => ({
        eventsSnippet: [
            [] as EventFormattedType[],
            {
                loadEventsSnippet: async (definition: EventOrPropType) => {
                    const eventsParams = toParams({
                        properties: {},
                        ...{ event: definition.name },
                        orderBy: ['-timestamp'],
                        limit: 5,
                    })
                    const events = await api.get(`api/event/?${eventsParams}`)
                    const propertyNames = Object.keys(events.results[0].properties).filter(
                        (key) => !keyMapping.event[key]
                    )
                    actions.loadPropertyDefinitions(propertyNames)
                    return events.results
                },
            },
        ],
        eventProperties: [
            [] as PropertyDefinition[],
            {
                loadPropertyDefinitions: async (properties) => {
                    const propertyDefinitions = await api.get(
                        `api/projects/@current/property_definitions/?properties=${properties}`
                    )
                    return propertyDefinitions.results
                },
                setPropertyDefinitions: (newProperty) => {
                    return values.eventProperties.map((prop) => (prop.id === newProperty.id ? newProperty : prop))
                },
            },
        ],
        editedDefinitions: [
            [] as PropertyDefinition[],
            {
                setDefinitionUpdateList: (property: PropertyDefinition) => {
                    const ids = values.editedDefinitions.flatMap((def) => def.id)
                    if (ids.includes(property.id)) {
                        return values.editedDefinitions.map((def) => (def === property.id ? property : def))
                    }
                    return [...values.editedDefinitions, property]
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
        definitionLoading: [
            false,
            {
                setDefinitionLoading: (_, { loading }) => loading,
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
        saveAllLoading: [
            false,
            {
                setSaveAllLoading: (_, { loading }) => loading,
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
        propertyDefinitionTags: [
            (selectors) => [selectors.eventProperties],
            (properties: PropertyDefinition[]): string[] => {
                const allTags = properties.flatMap(({ tags }) => tags).filter((a) => !!a) as string[]
                return uniqueBy(allTags, (item) => item).sort()
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        openDrawer: async ({ type, id }) => {
            const definitionType = type === 'event' ? 'event_definitions' : 'property_definitions'
            actions.setType(definitionType)
            const response = await api.get(`api/projects/@current/${definitionType}/${id}`)
            actions.setDefinition(response)
            actions.setDescription(response.description)
            actions.loadEventsSnippet(response)
        },
        saveNewTag: ({ tag }) => {
            if (values.definition?.tags?.includes(tag)) {
                errorToast('Oops! This tag is already set', 'This event already includes the proposed tag.')
                return
            }
            actions.setType('event_definitions')
            const currentTags = values.definition?.tags || []
            actions.updateDefinition({ tags: [...currentTags, tag] })
        },
        deleteTag: async ({ tag }, breakpoint) => {
            await breakpoint(100)
            const tags = values.definition?.tags?.filter((_tag: string) => _tag !== tag) || []
            actions.updateDefinition({ tags })
        },
        changeOwner: ({ ownerId }) => {
            actions.updateDefinition({ owner: ownerId })
        },
        saveNewPropertyTag: ({ tag, currentTags, propertyId }) => {
            if (currentTags?.includes(tag)) {
                errorToast('Oops! This tag is already set', 'This event already includes the proposed tag.')
                return
            }
            actions.setType('property_definitions')
            actions.updateDefinition({ tags: [...(currentTags || []), tag] }, propertyId)
        },
        deletePropertyTag: async ({ tag, currentTags, propertyId }, breakpoint) => {
            await breakpoint(100)
            actions.setType('property_definitions')
            const tags = currentTags?.filter((_tag: string) => _tag !== tag)
            actions.updateDefinition({ tags }, propertyId)
        },
        updateDefinition: async ({ payload, id }) => {
            actions.setDefinitionLoading(true)
            const definitionId = id ? id : values.definition?.id
            const response = await api.update(`api/projects/@current/${values.type}/${definitionId}/`, payload)
            actions.setDefinitionLoading(false)
            if (values.type === 'event_definitions') {
                actions.setDefinition(response)
                eventDefinitionsModel.actions.setEventDefinitions(response)
            } else {
                actions.setPropertyDefinitions(response)
            }
        },
        setPropertyDescription: ({ description, id }) => {
            const prop = values.eventProperties.find((p) => p.id === id)
            prop.description = description
            actions.setDefinitionUpdateList(prop)
        },
        updateAllDescriptions: async () => {
            actions.setSaveAllLoading(true)
            const propertyUpdates = values.editedDefinitions.map((def) => {
                return api.update(`api/projects/@current/property_definitions/${def.id}/`, {
                    description: def.description,
                })
            })
            actions.setType('event_definitions')
            if (values.description !== values.definition?.description) {
                const eventDescription = { description: values.description }
                actions.updateDefinition(eventDescription)
            }
            await Promise.all(propertyUpdates)
            actions.setSaveAllLoading(false)
        },
    }),
})
