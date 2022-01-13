import { kea } from 'kea'
import api from 'lib/api'
import { definitionDrawerLogicType } from './definitionDrawerLogicType'
import { EventDefinition, EventOrPropType, EventType, PropertyDefinition, UserBasicType } from '~/types'
import { errorToast, toParams, uniqueBy } from 'lib/utils'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { teamLogic } from 'scenes/teamLogic'
import {
    ApiDefinition,
    drawerTypeToApiTypeMap,
    TaxonomicId,
    TaxonomicType,
} from 'lib/components/DefinitionDrawer/types'

// Definition drawer that is event/event property/action/person/person property/etc. agnostic
// TODO: handle all taxonomic types
export const definitionDrawerLogic = kea<definitionDrawerLogicType>({
    path: ['lib', 'components', 'DefinitionDrawer', 'definitionDrawerLogic'],
    connect: {
        values: [teamLogic, ['currentTeamId']],
    },
    actions: () => ({
        openDrawer: (type: TaxonomicType, id?: TaxonomicId | null) => ({ type, id }),
        closeDrawer: true,
        // Definitions
        setDescription: (description: string) => ({ description }),
        setPropertyDescription: (description: string, id: string) => ({ description, id }),
        setNewTag: (tag: string) => ({ tag }),
        deleteTag: (tag: string) => ({ tag }),
        setTagLoading: (loading: boolean) => ({ loading }),
        setNewPropertyTag: (tag: string, currentTags?: string[], id?: string) => ({ tag, currentTags, id }),
        deletePropertyTag: (tag: string, currentTags?: string[], id?: string) => ({ tag, currentTags, id }),
        setDefinition: (definition: Partial<EventOrPropType>) => ({ definition }),
        setPropertyDefinition: (propertyDefinition: Partial<PropertyDefinition>, id?: string) => ({
            propertyDefinition,
            id,
        }),
        setPropertyDefinitionUpdateList: (id?: string) => ({ id }),
        changeOwner: (owner: UserBasicType) => ({ owner }),
        saveAll: true,
        setVisibilityById: (entry: Record<number, boolean>) => ({ entry }),
    }),
    loaders: ({ values }) => ({
        definition: [
            null as EventOrPropType | null,
            {
                loadDefinition: async ({ type, id }: { type: TaxonomicType; id: TaxonomicId }) => {
                    return await api.get(`api/projects/@current/${drawerTypeToApiTypeMap[type]}_definitions/${id}`)
                },
                saveDefinition: async ({
                    definition,
                    type,
                }: {
                    definition: Partial<EventOrPropType>
                    type: TaxonomicType
                }) => {
                    const definitionToSave = { ...definition } as ApiDefinition

                    if (type === TaxonomicType.Event) {
                        definitionToSave.owner = definition?.owner?.user?.id || undefined
                        definitionToSave.description = values.description
                    } else if (type === TaxonomicType.EventProperty) {
                        definitionToSave.description = values.description
                    }
                    return await api.update(
                        `api/projects/@current/${drawerTypeToApiTypeMap[type]}_definitions/${definitionToSave.id}`,
                        definitionToSave
                    )
                },
            },
        ],
        recentOccurrences: [
            [] as EventType[],
            {
                loadRecentOccurrences: async (definition: EventOrPropType | null) => {
                    const properties =
                        values.type === TaxonomicType.EventProperty
                            ? [
                                  {
                                      key: definition?.name,
                                      value: 'is_set',
                                      operator: 'is_set',
                                      type: TaxonomicType.Event,
                                  },
                              ]
                            : {}
                    const event = values.type === TaxonomicType.Event ? definition?.name : null
                    const eventsParams = toParams({
                        properties,
                        ...{ event },
                        orderBy: ['-timestamp'],
                        limit: 5,
                    })
                    const events = await api.get(`api/projects/${values.currentTeamId}/events/?${eventsParams}`)
                    return events.results
                },
            },
        ],
        propertiesDefinitions: [
            [] as PropertyDefinition[],
            {
                loadPropertiesDefinitions: async (propertyNames) => {
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
                openDrawer: (_, { type, id }) =>
                    !!id && [TaxonomicType.Event, TaxonomicType.EventProperty].includes(type),
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
            null as TaxonomicType | null,
            {
                openDrawer: (_, { type }) => type,
            },
        ],
        propertiesDefinitions: [
            [] as PropertyDefinition[],
            {
                setPropertyDefinition: (state, { propertyDefinition, id }) =>
                    state.map((p) => (p.id === id ? { ...p, ...propertyDefinition } : p)),
            },
        ],
        editedPropertyDefinitions: [
            [] as string[],
            {
                setPropertyDefinitionUpdateList: (state, { id }) => {
                    if (id && !state.includes(id)) {
                        return [...state, id]
                    }
                    return [...state]
                },
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
        propertiesDefinitionTags: [
            (selectors) => [selectors.propertiesDefinitions],
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
            if (!!id && values.drawerState) {
                actions.loadDefinition({ type, id })
            }
        },
        loadDefinitionSuccess: ({ definition }) => {
            actions.loadRecentOccurrences(definition)
            actions.setDescription(definition?.description || '')
        },
        loadRecentOccurrencesSuccess: ({ recentOccurrences }) => {
            if (values.type === TaxonomicType.Event) {
                const propertyNames = Object.keys(recentOccurrences[0].properties).filter(
                    (key) => !keyMapping.event[key]
                )
                actions.loadPropertiesDefinitions(propertyNames)
            }
        },
        saveDefinitionSuccess: ({ definition }) => {
            if (values.type === TaxonomicType.Event) {
                eventDefinitionsModel.actions.updateEventDefinition(definition as EventDefinition)
            } else if (values.type === TaxonomicType.EventProperty) {
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
        setNewPropertyTag: async ({ tag, currentTags, id }, breakpoint) => {
            actions.setTagLoading(true)
            if (currentTags?.includes(tag)) {
                errorToast('Oops! This tag is already set', 'This event already includes the proposed tag.')
                return
            }
            const tags = currentTags ? [...currentTags, tag] : []
            await breakpoint(100)
            actions.setTagLoading(false)
            actions.setPropertyDefinitionUpdateList(id)
            actions.setPropertyDefinition({ tags }, id)
        },
        deletePropertyTag: async ({ tag, currentTags, id }, breakpoint) => {
            await breakpoint(100)
            const tags = currentTags?.filter((_tag: string) => _tag !== tag)
            actions.setPropertyDefinitionUpdateList(id)
            actions.setPropertyDefinition({ tags }, id)
        },
        setPropertyDescription: ({ description, id }) => {
            actions.setPropertyDefinition({ description }, id)
            actions.setPropertyDefinitionUpdateList(id)
        },
        saveAll: () => {
            if (values.type) {
                actions.saveDefinition({ definition: { ...values.definition }, type: values.type })
                values.editedPropertyDefinitions.forEach((id) => {
                    const property = values.propertiesDefinitions.find((prop) => prop.id === id)
                    actions.saveDefinition({ definition: { ...property }, type: TaxonomicType.EventProperty })
                })
            }
            actions.closeDrawer()
        },
    }),
})
