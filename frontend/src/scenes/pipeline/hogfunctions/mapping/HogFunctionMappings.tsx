import { IconArrowRight, IconFilter, IconPlus, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonCollapsePanel,
    LemonLabel,
    LemonSelect,
    Tooltip,
} from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Group } from 'kea-forms'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { memo, useState } from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { groupsModel } from '~/models/groupsModel'
import { EntityTypes, HogFunctionConfigurationType, HogFunctionMappingType } from '~/types'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import { HogFunctionInputs } from '../HogFunctionInputs'

const humanize = (value: string): string => {
    // Simple replacement from something like MY_STRING-here to My string here
    return value
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
        <span className="flex items-center gap-4">
            <span>
                {eventSummary ? humanize(eventSummary) : <span className="text-muted-alt">All events</span>}{' '}
                {propertyFiltersCount ? (
                    <span className="text-muted-alt">
                        <Tooltip title={`Events have ${propertyFiltersCount} additional filters`}>
                            <IconFilter />
                        </Tooltip>
                    </span>
                ) : null}
            </span>
            <IconArrowRight className="text-muted-alt" />
            <span>{humanize(firstInputValue)}</span>
        </span>
    )
})

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
            {({
                value,
                onChange,
            }: {
                value: HogFunctionMappingType[]
                onChange: (mappings: HogFunctionMappingType[]) => void
            }) => {
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
                                                        icon: <IconX />,
                                                        onClick: () => {
                                                            onChange(value.filter((_, i) => i !== index))
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
