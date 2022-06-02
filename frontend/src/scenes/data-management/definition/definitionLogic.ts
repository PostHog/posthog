import { actions, afterMount, kea, key, props, path, selectors, reducers } from 'kea'
import { Breadcrumb, Definition, EventDefinition, PropertyDefinition } from '~/types'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import type { definitionLogicType } from './definitionLogicType'
import { getPropertyLabel } from 'lib/components/PropertyKeyInfo'

export enum DefinitionPageMode {
    View = 'view',
    Edit = 'edit',
}

export const createNewDefinition = (isEvent: boolean): Definition => ({
    id: 'new',
    name: `New ${isEvent ? 'Event' : 'Event property'}`,
    volume_30_day: null,
    query_usage_30_day: null,
})

export interface SetDefinitionProps {
    merge?: boolean
}

export interface DefinitionLogicProps {
    id?: Definition['id']
}

export const definitionLogic = kea<definitionLogicType>([
    path(['scenes', 'data-management', 'definition', 'definitionViewLogic']),
    props({} as DefinitionLogicProps),
    key((props) => props.id || 'new'),
    actions({
        setDefinition: (definition: Partial<Definition>, options: SetDefinitionProps = {}) => ({ definition, options }),
        loadDefinition: (id: Definition['id']) => ({ id }),
        setPageMode: (mode: DefinitionPageMode) => ({ mode }),
    }),
    reducers(() => ({
        mode: [
            DefinitionPageMode.View as DefinitionPageMode,
            {
                setPageMode: (_, { mode }) => mode,
            },
        ],
    })),
    loaders(({ values }) => ({
        definition: [
            createNewDefinition(values.isEvent),
            {
                setDefinition: ({ definition, options: { merge } }) =>
                    (merge ? { ...values.definition, ...definition } : definition) as Definition,
                loadDefinition: async ({ id }, breakpoint) => {
                    let definition = { ...values.definition }
                    try {
                        if (values.isEvent) {
                            // Event Definition
                            definition = await api.eventDefinitions.get({
                                eventDefinitionId: id,
                            })
                            eventDefinitionsModel
                                .findMounted()
                                ?.actions.updateEventDefinition(definition as EventDefinition)
                        } else {
                            // Event Property Definition
                            definition = await api.propertyDefinitions.get({
                                propertyDefinitionId: id,
                            })
                            propertyDefinitionsModel
                                .findMounted()
                                ?.actions.updatePropertyDefinition(definition as PropertyDefinition)
                        }
                        breakpoint()
                    } catch (response: any) {
                        throw response
                    }

                    return definition
                },
            },
        ],
    })),
    selectors({
        isEvent: [() => [router.selectors.location], ({ pathname }) => pathname.startsWith(urls.eventDefinitions())],
        singular: [(s) => [s.isEvent], (isEvent) => (isEvent ? 'event' : 'event property')],
        backDetailUrl: [
            (s) => [s.isEvent, s.definition],
            (isEvent, definition) =>
                isEvent ? urls.eventDefinition(definition.id) : urls.eventPropertyDefinition(definition.id),
        ],
        breadcrumbs: [
            (s) => [s.definition, s.isEvent],
            (definition, isEvent): Breadcrumb[] => {
                return [
                    {
                        name: `Data Management`,
                        path: isEvent ? urls.eventDefinitions() : urls.eventPropertyDefinitions(),
                    },
                    {
                        name: isEvent ? 'Events' : 'Event Properties',
                        path: isEvent ? urls.eventDefinitions() : urls.eventPropertyDefinitions(),
                    },
                    {
                        name: definition?.id !== 'new' ? getPropertyLabel(definition?.name) || 'Untitled' : 'Untitled',
                    },
                ]
            },
        ],
    }),
    afterMount(({ actions, values, props }) => {
        if (!props.id || props.id === 'new') {
            actions.setDefinition(createNewDefinition(values.isEvent))
        } else {
            actions.loadDefinition(props.id)
        }
    }),
])
