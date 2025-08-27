import { connect, kea, key, path, props } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { capitalizeFirstLetter } from 'lib/utils'
import { DefinitionLogicProps, definitionLogic } from 'scenes/data-management/definition/definitionLogic'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { propertyDefinitionsTableLogic } from 'scenes/data-management/properties/propertyDefinitionsTableLogic'
import { urls } from 'scenes/urls'

import { updatePropertyDefinitions } from '~/models/propertyDefinitionsModel'
import { tagsModel } from '~/models/tagsModel'
import { Definition, EventDefinition, PropertyDefinition } from '~/types'

import type { definitionEditLogicType } from './definitionEditLogicType'

export const definitionEditLogic = kea<definitionEditLogicType>([
    path(['scenes', 'data-management', 'definition', 'definitionDetailLogic']),
    props({} as DefinitionLogicProps),
    key((props) => props.id || 'new'),
    connect(({ id }: DefinitionLogicProps) => ({
        values: [definitionLogic({ id }), ['definition', 'isEvent', 'singular']],
        actions: [
            definitionLogic({ id }),
            ['setDefinition'],
            propertyDefinitionsTableLogic,
            ['setLocalPropertyDefinition'],
            eventDefinitionsTableLogic,
            ['setLocalEventDefinition'],
            tagsModel,
            ['loadTags'],
        ],
    })),
    forms(({ actions }) => ({
        editDefinition: {
            defaults: {} as Definition,
            errors: ({ name }) => ({
                name: !name ? 'You need to set a name' : null,
            }),
            submit: (definition) => {
                actions.saveDefinition(definition)
            },
        },
    })),
    loaders(({ values, actions }) => ({
        editDefinition: [
            {} as Definition,
            {
                saveDefinition: async (_, breakpoint) => {
                    let definition = { ...values.editDefinition }

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
                            propertyDefinitionData: _eventProperty,
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
                    actions.setDefinition(definition)
                    actions.loadTags() // reload tags in case new tags are being saved

                    router.actions.push(
                        values.isEvent ? urls.eventDefinition(definition.id) : urls.propertyDefinition(definition.id)
                    )
                    return definition
                },
            },
        ],
    })),

    subscriptions(({ actions }) => ({
        definition: (def) => {
            actions.resetEditDefinition(def)
        },
    })),

    beforeUnload(({ values, actions }) => ({
        enabled: () => values.editDefinitionChanged,
        message: `Leave?\nChanges you made will be discarded.`,
        onConfirm: () => {
            actions.resetEditDefinition(values.definition)
        },
    })),
])
