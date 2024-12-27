import { IconPlus, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonCollapsePanel, LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Group } from 'kea-forms'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { useState } from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { groupsModel } from '~/models/groupsModel'
import { EntityTypes, HogFunctionConfigurationType, HogFunctionMappingType } from '~/types'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import { HogFunctionInputs } from '../HogFunctionInputs'

export function HogFunctionMapping({
    index,
    mapping,
    onChange,
}: {
    index: number
    mapping: HogFunctionMappingType
    onChange: (mapping: HogFunctionMappingType | null) => void
}): JSX.Element | null {
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { showSource } = useValues(hogFunctionConfigurationLogic)

    return (
        <>
            <div className="p-3 space-y-2">
                <LemonLabel>Match events and actions</LemonLabel>
                <ActionFilter
                    filters={mapping.filters ?? ({} as any)}
                    setFilters={(f: any) => onChange({ ...mapping, filters: f })}
                    typeKey="match-group"
                    mathAvailability={MathAvailability.None}
                    hideRename
                    hideDuplicate
                    showNestedArrow={false}
                    actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
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
                    buttonProps={{
                        type: 'secondary',
                    }}
                    buttonCopy="Add event matcher"
                />
                <Group name={['mappings', index]}>
                    <HogFunctionInputs
                        configuration={mapping as HogFunctionConfigurationType}
                        setConfigurationValue={(key, value) => {
                            onChange({ ...mapping, [key]: value })
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
                            onChange({
                                ...mapping,
                                inputs_schema: [
                                    ...(mapping.inputs_schema ?? []),
                                    {
                                        type: 'string',
                                        key: `var_${(mapping.inputs_schema?.length ?? 0) + 1}`,
                                        label: '',
                                        required: false,
                                    },
                                ],
                            })
                        }}
                    >
                        Add input variable
                    </LemonButton>
                ) : null}
            </div>
        </>
    )
}

export function HogFunctionMappings(): JSX.Element | null {
    const { useMapping, mappingTemplates } = useValues(hogFunctionConfigurationLogic)
    const [activeKeys, setActiveKeys] = useState<number[]>([])

    if (!useMapping) {
        return null
    }

    return (
        <LemonField name="mappings">
            {({ value, onChange }) => {
                const addMapping = (template: string) => {
                    const mappingTemplate = mappingTemplates.find((t) => t.name === template)
                    if (mappingTemplate) {
                        const { name, ...mapping } = mappingTemplate

                        const inputs = mapping.inputs_schema
                            ? Object.fromEntries(
                                  mapping.inputs_schema
                                      .filter((m) => m.default !== undefined)
                                      .map((m) => [m.key, { value: structuredClone(m.default) }])
                              )
                            : {}
                        onChange([...mappings, { ...mapping, name, inputs }])

                        setActiveKeys([...activeKeys, mappings.length])
                    }
                    return
                }

                const addMappingButton = mappingTemplates.length ? (
                    <LemonSelect
                        placeholder="Add mapping"
                        onChange={(template) => {
                            addMapping(template)
                        }}
                        options={mappingTemplates.map((t) => ({
                            label: t.name,
                            value: t.name,
                        }))}
                    />
                ) : null

                const mappings = (value ?? []) as HogFunctionMappingType[]
                return (
                    <div className="p-3 border rounded bg-bg-light">
                        <div className="flex items-start justify-between">
                            <div className="flex-1">
                                <LemonLabel>Mappings</LemonLabel>
                                <p className="text-sm text-muted-alt">
                                    Configure which events should act as triggers including filters and custom
                                    transformations
                                </p>
                            </div>
                            {addMappingButton}
                        </div>

                        <div className="space-y-2">
                            {mappings.length ? (
                                <div className="-mx-3 border-t border-b">
                                    <LemonCollapse
                                        multiple
                                        embedded
                                        activeKeys={activeKeys}
                                        onChange={(activeKeys) => setActiveKeys(activeKeys)}
                                        panels={mappings.map(
                                            (mapping, index): LemonCollapsePanel<number> => ({
                                                key: index,
                                                header: {
                                                    children: mapping.name,
                                                    sideAction: {
                                                        icon: <IconX />,
                                                        onClick: () => {
                                                            onChange(mappings.filter((_, i) => i !== index))
                                                        },
                                                    },
                                                },
                                                className: 'p-0 bg-accent-light',
                                                content: (
                                                    <HogFunctionMapping
                                                        key={index}
                                                        index={index}
                                                        mapping={mapping}
                                                        onChange={(mapping) => {
                                                            if (!mapping) {
                                                                onChange(mappings.filter((_, i) => i !== index))
                                                            } else {
                                                                onChange(
                                                                    mappings.map((m, i) => (i === index ? mapping : m))
                                                                )
                                                            }
                                                        }}
                                                    />
                                                ),
                                            })
                                        )}
                                    />
                                </div>
                            ) : (
                                <LemonBanner type="warning" className="p-2">
                                    You have no mappings configured which effectively means the function is disabled as
                                    there is nothing to trigger it.
                                </LemonBanner>
                            )}
                        </div>
                    </div>
                )
            }}
        </LemonField>
    )
}
