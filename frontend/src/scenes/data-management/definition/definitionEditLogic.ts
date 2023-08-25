import { beforeUnmount, connect, kea, key, path, props } from 'kea'
import { Definition, EventDefinition, PropertyDefinition } from '~/types'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { updatePropertyDefinitions } from '~/models/propertyDefinitionsModel'
import {
    definitionLogic,
    DefinitionLogicProps,
    DefinitionPageMode,
} from 'scenes/data-management/definition/definitionLogic'
import type { definitionEditLogicType } from './definitionEditLogicType'
import { capitalizeFirstLetter } from 'lib/utils'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { propertyDefinitionsTableLogic } from 'scenes/data-management/properties/propertyDefinitionsTableLogic'
import { tagsModel } from '~/models/tagsModel'

export interface DefinitionEditLogicProps extends DefinitionLogicProps {
    definition: Definition
}

export const definitionEditLogic = kea<definitionEditLogicType>([
    path(['scenes', 'data-management', 'definition', 'definitionDetailLogic']),
    props({} as DefinitionEditLogicProps),
    key((props) => props.id || 'new'),
    connect(({ id }: DefinitionEditLogicProps) => ({
        values: [definitionLogic({ id }), ['isEvent', 'isProperty', 'singular', 'mode', 'hasTaxonomyFeatures']],
        actions: [
            definitionLogic({ id }),
            ['setDefinition', 'setPageMode'],
            propertyDefinitionsTableLogic,
            ['setLocalPropertyDefinition'],
            eventDefinitionsTableLogic,
            ['setLocalEventDefinition'],
            tagsModel,
            ['loadTags'],
        ],
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
                    } else {
                        // Event Property Definition
                        const _eventProperty = definition as PropertyDefinition
                        definition = await api.propertyDefinitions.update({
                            propertyDefinitionId: _eventProperty.id,
                            propertyDefinitionData: values.hasTaxonomyFeatures
                                ? _eventProperty
                                : // API does not accept other keys when on free tier
                                  { property_type: _eventProperty.property_type },
                        })
                        updatePropertyDefinitions({
                            [`event/${definition.name}`]: definition as PropertyDefinition,
                        })
                    }
                    breakpoint()

                    lemonToast.success(`${capitalizeFirstLetter(values.singular)} saved`)
                    // Update table values
                    if (values.isEvent) {
                        actions.setLocalEventDefinition(definition)
                    } else {
                        actions.setLocalPropertyDefinition(definition)
                    }
                    actions.setPageMode(DefinitionPageMode.View)
                    actions.setDefinition(definition)
                    actions.loadTags() // reload tags in case new tags are being saved
                    return definition
                },
            },
        ],
    })),
    beforeUnmount(({ actions }) => {
        actions.setPageMode(DefinitionPageMode.View)
    }),
])
