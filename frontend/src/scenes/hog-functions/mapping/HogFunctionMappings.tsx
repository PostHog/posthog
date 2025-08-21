import { useValues } from 'kea'
import { Group } from 'kea-forms'
import { memo, useEffect, useState } from 'react'

import { IconArrowRight, IconEllipsis, IconFilter, IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonCollapsePanel,
    LemonDialog,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { groupsModel } from '~/models/groupsModel'
import { EntityTypes, HogFunctionConfigurationType, HogFunctionMappingType } from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'

const humanize = (value: string): string => {
    const fallback = typeof value === 'string' ? (value ?? '') : ''

    // Simple replacement from something like MY_STRING-here to My string here
    return fallback
        .toLowerCase()
        .replace(/_/g, ' ')
        .replace(/-/g, ' ')
        .replace(/\b\w/g, (char) => char.toUpperCase())
}

const MappingSummary = memo(function MappingSummary({
    mapping,
}: {
    mapping: HogFunctionMappingType
}): JSX.Element | null {
    const events = mapping.filters?.events?.map((event) => event.name ?? event.id) ?? []
    const actions = mapping.filters?.actions?.map((action) => action.name ?? action.id) ?? []

    const propertyFiltersCount =
        (mapping.filters?.events?.filter((event) => event.properties?.length ?? 0) ?? []).length +
        (mapping.filters?.actions?.filter((action) => action.properties?.length ?? 0) ?? []).length

    const eventSummary = [...events, ...actions].join(', ')

    const firstInput = mapping.inputs_schema?.[0]
    const firstInputValue = (firstInput?.key ? mapping.inputs?.[firstInput.key]?.value : null) ?? '(custom value)'

    return (
        <span className="flex flex-1 gap-4 items-center">
            <span>
                {eventSummary ? humanize(eventSummary) : <span className="text-secondary">All events</span>}{' '}
                {propertyFiltersCount ? (
                    <span className="text-secondary">
                        <Tooltip title={`Events have ${propertyFiltersCount} additional filters`}>
                            <IconFilter />
                        </Tooltip>
                    </span>
                ) : null}
            </span>
            <IconArrowRight className="text-secondary" />
            <span>
                {mapping.name
                    ? humanize(mapping.name)
                    : typeof firstInputValue === 'object'
                      ? JSON.stringify(firstInputValue)
                      : humanize(firstInputValue)}
            </span>
            <span className="flex-1" />
            {mapping.disabled ? <LemonTag type="danger">Disabled</LemonTag> : null}
        </span>
    )
})

export function HogFunctionMapping({
    index,
    mapping,
    onChange,
    parentConfiguration,
}: {
    index: number
    mapping: HogFunctionMappingType
    onChange: (mapping: HogFunctionMappingType | null) => void
    parentConfiguration: HogFunctionConfigurationType
}): JSX.Element | null {
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { showSource, sampleGlobalsWithInputs } = useValues(hogFunctionConfigurationLogic)

    return (
        <>
            <div className="p-3 pl-10 deprecated-space-y-2">
                {mapping.disabled ? (
                    <LemonBanner
                        type="warning"
                        className="p-2"
                        action={{
                            children: 'Enable',
                            onClick: () => onChange({ ...mapping, disabled: false }),
                        }}
                    >
                        This mapping is disabled. It will not trigger the function.
                    </LemonBanner>
                ) : null}
                <LemonLabel>Match events and actions</LemonLabel>
                <ActionFilter
                    filters={mapping.filters ?? ({} as any)}
                    setFilters={(f: any) => onChange({ ...mapping, filters: f })}
                    typeKey={`match-group-${index}`}
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
                    <CyclotronJobInputs
                        configuration={{
                            inputs_schema: mapping.inputs_schema ?? [],
                            inputs: mapping.inputs ?? {},
                        }}
                        parentConfiguration={{
                            inputs_schema: parentConfiguration.inputs_schema ?? [],
                            inputs: parentConfiguration.inputs ?? {},
                        }}
                        onInputSchemaChange={(schema) => {
                            onChange({ ...mapping, inputs_schema: schema })
                        }}
                        onInputChange={(key, value) => {
                            onChange({ ...mapping, inputs: { ...mapping.inputs, [key]: value } })
                        }}
                        showSource={showSource}
                        sampleGlobalsWithInputs={sampleGlobalsWithInputs}
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
    const { useMapping, mappingTemplates, configuration } = useValues(hogFunctionConfigurationLogic)
    const [activeKeys, setActiveKeys] = useState<number[]>([])

    // If there is only one mapping template, then we start it expanded
    useEffect(() => {
        if (configuration.mappings?.length === 1) {
            setActiveKeys([0])
        }
    }, [configuration.mappings?.length])

    if (!useMapping) {
        return null
    }

    return (
        <LemonField name="mappings">
            {({
                value,
                onChange,
            }: {
                value: HogFunctionMappingType[] | undefined
                onChange: (mappings: HogFunctionMappingType[]) => void
            }) => {
                if (!value) {
                    // Tricky there can be a race where this renders before the parent is un-rendered
                    return <></>
                }

                const addMapping = (template: string): void => {
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
                        onChange([...value, { ...mapping, name, inputs }])
                        setActiveKeys([...activeKeys, value.length])
                    }
                    return
                }

                const duplicateMapping = (mapping: HogFunctionMappingType): void => {
                    const index = value.findIndex((m) => m === mapping)
                    if (index !== -1) {
                        const newMappings = [...value]
                        newMappings.splice(index + 1, 0, mapping)
                        onChange(newMappings)
                        setActiveKeys([index + 1])
                    }
                }

                const removeMapping = (mapping: HogFunctionMappingType): void => {
                    const index = value.findIndex((m) => m === mapping)
                    if (index !== -1) {
                        onChange(value.filter((_, i) => i !== index))
                        setActiveKeys(activeKeys.filter((i) => i !== index))
                    }
                }

                const toggleDisabled = (mapping: HogFunctionMappingType): void => {
                    const index = value.findIndex((m) => m === mapping)
                    if (index !== -1) {
                        onChange(value.map((m, i) => (i === index ? { ...m, disabled: !m.disabled } : m)))
                    }
                }

                const renameMapping = (mapping: HogFunctionMappingType): void => {
                    LemonDialog.openForm({
                        title: 'Rename mapping',
                        initialValues: { mappingName: mapping.name },
                        content: (
                            <LemonField name="mappingName">
                                <LemonInput
                                    data-attr="mapping-name"
                                    placeholder="Please enter the new name"
                                    autoFocus
                                />
                            </LemonField>
                        ),
                        errors: {
                            mappingName: (name) => (!name ? 'You must enter a name' : undefined),
                        },
                        onSubmit: async ({ mappingName }) => {
                            const index = value.findIndex((m) => m === mapping)
                            if (index !== -1) {
                                onChange(value.map((m, i) => (i === index ? { ...m, name: mappingName } : m)))
                            }
                        },
                    })
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

                return (
                    <div className="p-3 rounded border bg-surface-primary">
                        <div className="flex justify-between items-start">
                            <div className="flex-1">
                                <LemonLabel>Mappings</LemonLabel>
                                <p className="text-sm text-secondary">
                                    Configure which events should act as triggers including filters and custom
                                    transformations
                                </p>
                            </div>
                            {addMappingButton}
                        </div>

                        <div className="deprecated-space-y-2">
                            {value.length ? (
                                <div className="-mx-3 border-t border-b">
                                    <LemonCollapse
                                        multiple
                                        embedded
                                        activeKeys={activeKeys}
                                        onChange={(activeKeys) => setActiveKeys(activeKeys)}
                                        panels={value.map(
                                            (mapping, index): LemonCollapsePanel<number> => ({
                                                key: index,
                                                header: {
                                                    children: <MappingSummary mapping={mapping} />,
                                                    sideAction: {
                                                        icon: <IconEllipsis />,
                                                        dropdown: {
                                                            overlay: (
                                                                <div className="deprecated-space-y-px">
                                                                    <LemonButton
                                                                        onClick={() => toggleDisabled(mapping)}
                                                                    >
                                                                        {mapping.disabled ? 'Enable' : 'Disable'}
                                                                    </LemonButton>
                                                                    <LemonButton onClick={() => renameMapping(mapping)}>
                                                                        Rename
                                                                    </LemonButton>
                                                                    <LemonButton
                                                                        onClick={() => duplicateMapping(mapping)}
                                                                    >
                                                                        Duplicate
                                                                    </LemonButton>
                                                                    <LemonButton
                                                                        status="danger"
                                                                        onClick={() => removeMapping(mapping)}
                                                                    >
                                                                        Remove
                                                                    </LemonButton>
                                                                </div>
                                                            ),
                                                        },
                                                    },
                                                },
                                                className: 'p-0 bg-accent-light',
                                                content: (
                                                    <HogFunctionMapping
                                                        parentConfiguration={configuration}
                                                        key={index}
                                                        index={index}
                                                        mapping={mapping}
                                                        onChange={(mapping) => {
                                                            if (!mapping) {
                                                                onChange(value.filter((_, i) => i !== index))
                                                            } else {
                                                                onChange(
                                                                    value.map((m, i) => (i === index ? mapping : m))
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
