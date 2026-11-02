import { ReactNode } from 'react'

import { ChartOptionNumberInput } from './ChartOptionNumberInput'
import { ChartOptionSelect } from './ChartOptionSelect'
import { ChartOptionSwitch } from './ChartOptionSwitch'
import { ChartOptionTextInput } from './ChartOptionTextInput'
import { ChartOptionToggleGroup } from './ChartOptionToggleGroup'
import { ChartOptionWarning } from './ChartOptionWarning'
import {
    DISPLAY_OPTION_GROUPS,
    DISPLAY_OPTION_TABS,
    DISPLAY_OPTIONS,
    DisplayOptionBinding,
    DisplayOptionBindings,
    DisplayOptionDefinition,
    DisplayOptionGroupKey,
    DisplayOptionItem,
    DisplayOptionSection,
    DisplayOptionTab,
} from './displayOptions'

type AnyBinding<C> = DisplayOptionBinding<C, any>

export interface DisplayOptionGroupOverride {
    title?: string
    // `null` drops the group's tooltip on a surface where it doesn't apply.
    tooltip?: string | null
}

export interface BuildDisplayOptionsSettings {
    // Lists every group under one tab, for a surface with too few options to need tabs.
    singleTab?: boolean
    groups?: Partial<Record<DisplayOptionGroupKey, DisplayOptionGroupOverride>>
}

function renderControl<C>(definition: DisplayOptionDefinition, binding: AnyBinding<C>, c: C): ReactNode {
    if (binding.render) {
        return binding.render(c)
    }
    const label = definition.label
    const visibleLabel = definition.hideLabel ? undefined : label
    const value = binding.value?.(c)
    const onChange = (next: unknown): void => binding.onChange?.(next, c)
    const disabledReason = binding.disabledReason?.(c) ?? undefined
    const dataAttr = binding.dataAttr

    switch (definition.control) {
        case 'checkbox':
            return (
                <ChartOptionSwitch
                    label={label}
                    info={definition.info}
                    checked={!!value}
                    onChange={onChange}
                    disabledReason={disabledReason}
                    data-attr={dataAttr}
                />
            )
        case 'number':
            return (
                <ChartOptionNumberInput
                    label={label}
                    info={definition.info}
                    value={value}
                    min={definition.min}
                    max={definition.max}
                    suffix={binding.suffix?.(c) ?? definition.suffix}
                    placeholder={binding.placeholder?.(c) ?? definition.placeholder}
                    disabledReason={disabledReason}
                    onChange={onChange}
                    data-attr={dataAttr}
                />
            )
        case 'text':
            return (
                <ChartOptionTextInput
                    label={visibleLabel}
                    info={definition.info}
                    value={value}
                    placeholder={binding.placeholder?.(c) ?? definition.placeholder}
                    onChange={onChange}
                    data-attr={dataAttr}
                />
            )
        case 'select':
        case 'toggle': {
            const Control = definition.control === 'select' ? ChartOptionSelect : ChartOptionToggleGroup
            return (
                <Control
                    label={visibleLabel}
                    info={definition.info}
                    value={value}
                    options={binding.options?.(c) ?? [...(definition.options ?? [])]}
                    onChange={onChange}
                    disabledReason={disabledReason}
                    data-attr={dataAttr}
                />
            )
        }
        case 'custom':
            return null
    }
}

function renderOption<C>(definition: DisplayOptionDefinition, binding: AnyBinding<C>, c: C): ReactNode {
    const control = renderControl(definition, binding, c)
    const warning = binding.warning?.(c)
    const content = warning ? (
        <>
            {control}
            <ChartOptionWarning>{warning}</ChartOptionWarning>
        </>
    ) : (
        control
    )
    return definition.nested ? <div className="pl-4">{content}</div> : content
}

// Turns one surface's bindings into tabs → sections → rendered options, in the shared order.
// `count` is the number of options set away from their default, badged on the Options button.
export function buildDisplayOptions<C>(
    bindings: DisplayOptionBindings<C>,
    c: C,
    { singleTab = false, groups: overrides = {} }: BuildDisplayOptionsSettings = {}
): { tabs: DisplayOptionTab[]; count: number } {
    const definitions: readonly DisplayOptionDefinition[] = DISPLAY_OPTIONS
    const itemsByGroup = new Map<DisplayOptionGroupKey, DisplayOptionItem[]>()
    const countByGroup = new Map<DisplayOptionGroupKey, number>()

    for (const definition of definitions) {
        const name = definition.name as keyof DisplayOptionBindings<C>
        const binding = bindings[name] as AnyBinding<C> | undefined
        if (!binding || !binding.showCondition(c)) {
            continue
        }
        const group = definition.group
        itemsByGroup.set(group, [
            ...(itemsByGroup.get(group) ?? []),
            { name, element: renderOption(definition, binding, c) },
        ])
        countByGroup.set(group, (countByGroup.get(group) ?? 0) + Number(binding.changedCount?.(c) ?? 0))
    }

    const allTabs: DisplayOptionTab[] = DISPLAY_OPTION_TABS.map((tab) => {
        const groups = DISPLAY_OPTION_GROUPS.filter((group) => group.tab === tab.key)
        const sections = groups.flatMap((group): DisplayOptionSection[] => {
            const items = itemsByGroup.get(group.key)
            if (!items) {
                return []
            }
            const override = overrides[group.key]
            const definitionTooltip = 'tooltip' in group ? group.tooltip : undefined
            return [
                {
                    key: group.key,
                    title: override?.title ?? ('title' in group ? group.title : undefined),
                    tooltip: override?.tooltip === null ? undefined : (override?.tooltip ?? definitionTooltip),
                    dataAttr: 'dataAttr' in group ? group.dataAttr : undefined,
                    items,
                },
            ]
        })
        const count = groups.reduce((sum, group) => sum + (countByGroup.get(group.key) ?? 0), 0)
        return { key: tab.key, label: tab.label, sections, count }
    })

    const tabs = (
        singleTab
            ? [
                  {
                      key: 'general' as const,
                      label: 'General',
                      sections: allTabs.flatMap((tab) => tab.sections),
                      count: allTabs.reduce((sum, tab) => sum + tab.count, 0),
                  },
              ]
            : allTabs
    ).filter((tab) => tab.sections.length > 0)

    return { tabs, count: tabs.reduce((sum, tab) => sum + tab.count, 0) }
}
