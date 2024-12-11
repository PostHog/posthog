import { IconPlus, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonLabel } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Group } from 'kea-forms'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import React from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { groupsModel } from '~/models/groupsModel'
import { EntityTypes, FilterType, HogFunctionConfigurationType, HogFunctionMappingType } from '~/types'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import { HogFunctionInputs } from '../HogFunctionInputs'

const defaultMatchGroupFilters = {
    // TODO: or screen?
    events: [{ id: '$pageview', name: '$pageview', type: EntityTypes.EVENTS, order: 0, properties: [] }],
    actions: [],
}

export function HogFunctionMapping(): JSX.Element | null {
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { useMapping, showSource } = useValues(hogFunctionConfigurationLogic)

    if (!useMapping) {
        return null
    }

    return (
        <LemonField name="mappings">
            {({ value, onChange }) => {
                const mappings = (value ?? []) as HogFunctionMappingType[]
                return (
                    <>
                        {mappings.map((mapping, index) => (
                            <div key={index} className="border bg-bg-light rounded p-3 space-y-2">
                                <div className="flex items-center justify-between w-full gap-2">
                                    <LemonLabel info="When an event matches these filters, the function is run with the appended inputs.">
                                        Mapping #{index + 1}
                                    </LemonLabel>
                                    {mappings.length > 1 ? (
                                        <LemonButton
                                            key="delete"
                                            icon={<IconTrash />}
                                            title="Delete graph series"
                                            data-attr={`delete-prop-filter-${index}`}
                                            noPadding
                                            onClick={() => onChange(mappings.filter((_, i) => i !== index))}
                                        />
                                    ) : null}
                                </div>
                                <ActionFilter
                                    bordered
                                    filters={(mapping.filters ?? {}) as FilterType}
                                    setFilters={(f) =>
                                        onChange(mappings.map((m, i) => (i === index ? { ...m, filters: f } : m)))
                                    }
                                    typeKey={`match-group-${index}`}
                                    mathAvailability={MathAvailability.None}
                                    hideRename
                                    hideDuplicate
                                    showNestedArrow={false}
                                    actionsTaxonomicGroupTypes={[
                                        TaxonomicFilterGroupType.Events,
                                        TaxonomicFilterGroupType.Actions,
                                    ]}
                                    propertiesTaxonomicGroupTypes={[
                                        TaxonomicFilterGroupType.EventProperties,
                                        TaxonomicFilterGroupType.EventFeatureFlags,
                                        TaxonomicFilterGroupType.Elements,
                                        TaxonomicFilterGroupType.PersonProperties,
                                        TaxonomicFilterGroupType.HogQLExpression,
                                        ...groupsTaxonomicTypes,
                                    ]}
                                    propertyFiltersPopover
                                    addFilterDefaultOptions={{
                                        id: '$pageview',
                                        name: '$pageview',
                                        type: EntityTypes.EVENTS,
                                    }}
                                    buttonCopy="Add event matcher"
                                />
                                <Group name={['mappings', index]}>
                                    <HogFunctionInputs
                                        configuration={mapping as HogFunctionConfigurationType}
                                        setConfigurationValue={(key, value) => {
                                            onChange(mappings.map((m, i) => (i === index ? { ...m, [key]: value } : m)))
                                        }}
                                    />
                                </Group>
                                {showSource ? (
                                    <LemonButton
                                        icon={<IconPlus />}
                                        size="small"
                                        type="secondary"
                                        className="my-4"
                                        onClick={() => {
                                            onChange(
                                                mappings.map((m, i) => {
                                                    if (i !== index) {
                                                        return m
                                                    }
                                                    const inputs_schema = m.inputs_schema ?? []
                                                    return {
                                                        ...m,
                                                        inputs_schema: [
                                                            ...inputs_schema,
                                                            {
                                                                type: 'string',
                                                                key: `var_${inputs_schema.length + 1}`,
                                                                label: '',
                                                                required: false,
                                                            },
                                                        ],
                                                    }
                                                })
                                            )
                                        }}
                                    >
                                        Add input variable
                                    </LemonButton>
                                ) : null}
                            </div>
                        ))}
                        <div className="border bg-bg-light rounded p-3 space-y-2">
                            <LemonButton
                                type="tertiary"
                                data-attr="add-action-event-button"
                                icon={<IconPlusSmall />}
                                onClick={() => {
                                    const inputsSchema =
                                        mappings.length > 0
                                            ? structuredClone(mappings[mappings.length - 1].inputs_schema)
                                            : {}
                                    const inputs =
                                        mappings.length > 0
                                            ? Object.fromEntries(
                                                  (mappings[mappings.length - 1].inputs_schema || [])
                                                      .filter((m) => m.default !== undefined)
                                                      .map((m) => [m.key, { value: structuredClone(m.default) }])
                                              )
                                            : {}
                                    onChange([
                                        ...mappings,
                                        {
                                            inputs_schema: inputsSchema,
                                            inputs: inputs,
                                            filters: defaultMatchGroupFilters,
                                        },
                                    ])
                                }}
                            >
                                Add mapping
                            </LemonButton>
                        </div>
                    </>
                )
            }}
        </LemonField>
    )
}
