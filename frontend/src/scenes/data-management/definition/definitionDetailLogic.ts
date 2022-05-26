import { kea, props, path, actions, key, selectors } from 'kea'
import { Definition, EventDefinition, PropertyDefinition } from '~/types'
import type { definitionDetailLogicType } from './definitionDetailLogicType'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/components/lemonToast'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

export interface SetDefinitionProps {
    merge?: boolean
}

export interface DefinitionDetailLogicProps {
    id?: Definition['id']
    definition: Definition
}

export const definitionDetailLogic = kea<definitionDetailLogicType>([
    path(['scenes', 'data-management', 'definition', 'definitionDetailLogic']),
    props({} as DefinitionDetailLogicProps),
    key((props) => props.id || 'new'),
    actions({
        setEvent: (
            definition: Partial<EventDefinition> | Partial<PropertyDefinition>,
            options: SetDefinitionProps
        ) => ({ definition, options }),
    }),
    forms(({ actions, props }) => ({
        action: {
            defaults: { ...props.definition } as Definition,
            errors: ({ name }) => ({
                name: !name ? 'You need to set a name' : null,
            }),
            submit: (definition) => {
                actions.saveDefinition(definition)
            },
        },
    })),
    selectors({
        isEvent: [() => [router.selectors.location], ({ pathname }) => pathname.startsWith(urls.eventDefinitions())],
    }),
    loaders(({ props, values }) => ({
        definition: [
            { ...props.definition } as Definition,
            {
                setDefinition: ({ definition, options: { merge } }) =>
                    (merge ? { ...values.definition, ...definition } : definition) as Definition,
                saveDefinition: async (updatedDefinition: Definition, breakpoint) => {
                    let definition = { ...updatedDefinition }

                    try {
                        if (values.isEvent) {
                            // Event Definition
                            const _event = definition as EventDefinition
                            definition = await api.eventDefinitions.update({
                                eventDefinitionId: _event.id,
                                eventDefinitionData: {
                                    ..._event,
                                    owner: _event.owner?.id ?? null,
                                    verified: !!_event.verified,
                                },
                            })
                            eventDefinitionsModel
                                .findMounted()
                                ?.actions.updateEventDefinition(definition as EventDefinition)
                        } else {
                            // Event Property Definition
                            const _eventProperty = definition as PropertyDefinition
                            definition = await api.propertyDefinitions.update({
                                propertyDefinitionId: _eventProperty.id,
                                propertyDefinitionData: _eventProperty,
                            })
                            propertyDefinitionsModel
                                .findMounted()
                                ?.actions.updatePropertyDefinition(definition as PropertyDefinition)
                        }
                        breakpoint()
                    } catch (response: any) {
                        throw response
                    }

                    lemonToast.success(`${values.isEvent ? 'Event' : 'Event property'} saved`)
                    eventDefinitionsModel.actions.loadEventDefinitions() // reload definitions so they are immediately available
                    return definition
                },
            },
        ],
    })),
])
