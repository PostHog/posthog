import { kea, props, path, key, connect } from 'kea'
import { Definition, EventDefinition, PropertyDefinition } from '~/types'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/components/lemonToast'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { definitionLogic, DefinitionLogicProps } from 'scenes/data-management/definition/definitionLogic'

import type { definitionEditLogicType } from './definitionEditLogicType'

export const definitionEditLogic = kea<definitionEditLogicType>([
    path(['scenes', 'data-management', 'definition', 'definitionDetailLogic']),
    props({} as DefinitionLogicProps),
    key((props) => props.id || 'new'),
    connect((props: DefinitionLogicProps) => ({
        values: [definitionLogic(props), ['definition', 'isEvent']],
        actions: [definitionLogic(props), ['setDefinition']],
    })),
    forms(({ actions, values }) => ({
        action: {
            defaults: { ...values.definition } as Definition,
            errors: ({ name }) => ({
                name: !name ? 'You need to set a name' : null,
            }),
            submit: (definition) => {
                actions.saveDefinition(definition)
            },
        },
    })),
    loaders(({ values }) => ({
        definition: [
            { ...values.definition } as Definition,
            {
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
