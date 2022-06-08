import { beforeUnmount, connect, kea, key, path, props } from 'kea'
import { Definition, EventDefinition, PropertyDefinition } from '~/types'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/components/lemonToast'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import {
    definitionLogic,
    DefinitionLogicProps,
    DefinitionPageMode,
} from 'scenes/data-management/definition/definitionLogic'
import type { definitionEditLogicType } from './definitionEditLogicType'
import { capitalizeFirstLetter } from 'lib/utils'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { eventPropertyDefinitionsTableLogic } from 'scenes/data-management/event-properties/eventPropertyDefinitionsTableLogic'

export interface DefinitionEditLogicProps extends DefinitionLogicProps {
    definition: Definition
}

export const definitionEditLogic = kea<definitionEditLogicType>([
    path(['scenes', 'data-management', 'definition', 'definitionDetailLogic']),
    props({} as DefinitionEditLogicProps),
    key((props) => props.id || 'new'),
    connect(({ id }: DefinitionEditLogicProps) => ({
        values: [definitionLogic({ id }), ['isEvent', 'singular', 'mode', 'hasTaxonomyFeatures']],
        actions: [definitionLogic({ id }), ['setDefinition', 'setPageMode']],
    })),
    forms(({ actions, props }) => ({
        definition: {
            defaults: { ...props.definition } as Definition,
            errors: ({ name }) => ({
                name: !name ? 'You need to set a name' : null,
            }),
            submit: (definition) => {
                actions.saveDefinition(definition)
            },
        },
    })),
    loaders(({ values, props, actions }) => ({
        definition: [
            { ...props.definition } as Definition,
            {
                saveDefinition: async (_, breakpoint) => {
                    let definition = { ...values.definition }

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

                    lemonToast.success(`${capitalizeFirstLetter(values.singular)} saved`)
                    eventDefinitionsModel.actions.loadEventDefinitions(true) // reload definitions so they are immediately available
                    // Update table values
                    if (values.isEvent) {
                        eventDefinitionsTableLogic.actions.setLocalEventDefinition(definition)
                    } else {
                        eventPropertyDefinitionsTableLogic.actions.setLocalEventPropertyDefinition(definition)
                    }
                    actions.setPageMode(DefinitionPageMode.View)
                    actions.setDefinition(definition)
                    return definition
                },
            },
        ],
    })),
    beforeUnmount(({ actions }) => {
        actions.setPageMode(DefinitionPageMode.View)
    }),
])
