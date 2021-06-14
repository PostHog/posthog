import { kea } from 'kea'
import api from 'lib/api'
import { definitionDrawerLogicType } from './definitionDrawerLogicType'
import { IndexedTrendResult } from 'scenes/trends/trendsLogic'
import { EventDefinition, EventFormattedType, EventOrPropType } from '~/types'
import { errorToast, toParams, uniqueBy } from 'lib/utils'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { valueType } from 'antd/lib/statistic/utils'

export const definitionDrawerLogic = kea<definitionDrawerLogicType<EventOrPropType>>({
    actions: () => ({
        openDrawer: (type: string, id: string) => ({ type, id }),
        setType: (type: string) => ({ type }),
        setDefinition: (definition: EventOrPropType) => ({ definition }),
        updateDefinition: (payload: Partial<EventOrPropType>) => ({ payload }),
        saveNewTag: (tag: string) => ({ tag }),
        deleteTag: (tag: string) => ({ tag }),
        setDefinitionLoading: (loading: boolean) => ({ loading }),
        changeOwner: (ownerId: valueType) => ({ ownerId }),
        setDescription: (description: string) => ({ description }),
        setDescriptionEditing: (editing: boolean) => ({ editing }),
        setGraphResults: (results: any) => ({ results }),
        setVisibilityById: (entry: Record<number, boolean>) => ({ entry }),
        closeDrawer: true,
        cancelDescription: true,
        saveDescription: true,
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
                        limit: 5,
                    })
                    const events = await api.get(`api/event/?${urlParams}`)
                    return events.results
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
            (definitions: EventDefinition[]): string[] =>
                uniqueBy(
                    definitions.flatMap(({ tags }) => tags),
                    (item) => item
                ).sort(),
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
            if (values.definition?.tags.includes(tag)) {
                errorToast('Oops! This tag is already set', 'This event already includes the proposed tag.')
                return
            }
            const currentTags = values.definition?.tags || []
            actions.updateDefinition({ tags: [...currentTags, tag] })
        },
        deleteTag: async ({ tag }, breakpoint) => {
            await breakpoint(100)
            const tags = values.definition?.tags.filter((_tag: string) => _tag !== tag)
            actions.updateDefinition({ tags })
        },
        changeOwner: ({ ownerId }) => {
            actions.updateDefinition({ owner: ownerId })
        },
        cancelDescription: () => {
            actions.setDescription(values.definition?.description || '')
            actions.setDescriptionEditing(false)
        },
        saveDescription: () => {
            actions.setDescriptionEditing(false)
            actions.updateDefinition({ description: values.description })
        },
        updateDefinition: async ({ payload }) => {
            actions.setDefinitionLoading(true)
            const response = await api.update(`api/projects/@current/${values.type}/${values.definition?.id}/`, payload)
            actions.setDefinition(response)
            actions.setDefinitionLoading(false)
            eventDefinitionsModel.actions.setEventDefinitions(response)
        },
    }),
})
