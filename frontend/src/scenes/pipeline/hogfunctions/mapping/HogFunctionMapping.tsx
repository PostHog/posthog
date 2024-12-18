import { IconPlus, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Group } from 'kea-forms'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { getDefaultEventName } from 'lib/utils/getAppContext'
import { useState } from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { groupsModel } from '~/models/groupsModel'
import { EntityTypes, FilterType, HogFunctionConfigurationType, HogFunctionMappingType } from '~/types'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import { HogFunctionInputs } from '../HogFunctionInputs'

export function HogFunctionMapping(): JSX.Element | null {
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { useMapping, showSource, mappingTemplates } = useValues(hogFunctionConfigurationLogic)
    const [selectedMappingTemplate, setSelectedMappingTemplate] = useState<string | null>(null)

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
                                    <LemonButton
                                        key="delete"
                                        icon={<IconTrash />}
                                        title="Delete graph series"
                                        data-attr={`delete-prop-filter-${index}`}
                                        noPadding
                                        onClick={() => onChange(mappings.filter((_, i) => i !== index))}
                                    />
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
                            <LemonLabel>New Mapping</LemonLabel>
                            <div className="flex gap-2">
                                {mappingTemplates.length ? (
                                    <LemonSelect
                                        placeholder="Select a template"
                                        value={selectedMappingTemplate}
                                        onChange={setSelectedMappingTemplate}
                                        options={mappingTemplates.map((t) => ({
                                            label: t.name,
                                            value: t.name,
                                        }))}
                                    />
                                ) : null}
                                <LemonButton
                                    type="secondary"
                                    data-attr="add-action-event-button"
                                    icon={<IconPlusSmall />}
                                    disabledReason={
                                        mappingTemplates.length && !selectedMappingTemplate
                                            ? 'Select a mapping template'
                                            : undefined
                                    }
                                    onClick={() => {
                                        if (selectedMappingTemplate) {
                                            const mappingTemplate = mappingTemplates.find(
                                                (t) => t.name === selectedMappingTemplate
                                            )
                                            if (mappingTemplate) {
                                                const { name, ...mapping } = mappingTemplate
                                                const inputs = mapping.inputs_schema
                                                    ? Object.fromEntries(
                                                          mapping.inputs_schema
                                                              .filter((m) => m.default !== undefined)
                                                              .map((m) => [
                                                                  m.key,
                                                                  { value: structuredClone(m.default) },
                                                              ])
                                                      )
                                                    : {}
                                                onChange([...mappings, { ...mapping, inputs }])
                                            }
                                            setSelectedMappingTemplate(null)
                                            return
                                        }

                                        const newMapping = {
                                            inputs_schema: [],
                                            inputs: {},
                                            filters: {
                                                events: [
                                                    {
                                                        id: getDefaultEventName(),
                                                        name: getDefaultEventName(),
                                                        type: EntityTypes.EVENTS,
                                                        order: 0,
                                                        properties: [],
                                                    },
                                                ],
                                                actions: [],
                                            },
                                        }
                                        onChange([...mappings, newMapping])
                                    }}
                                >
                                    Add mapping
                                </LemonButton>
                            </div>
                        </div>
                    </>
                )
            }}
        </LemonField>
    )
}
