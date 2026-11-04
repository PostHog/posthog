import { ReactNode } from 'react'

import { MetricDirectionColorPickers } from 'lib/components/Metric/MetricDirectionColorPickers'

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
    DirectionColors,
} from './displayOptions'

type AnyBinding<C> = DisplayOptionBinding<C, any>

export interface DisplayOptionGroupOverride {
    title?: string
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
    const visibleLabel = definition.hideLabel || definition.stacked ? undefined : label
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
        case 'colors': {
            const colors = value as DirectionColors
            return (
                <MetricDirectionColorPickers
                    className="gap-2"
                    increaseColor={colors.increase}
                    decreaseColor={colors.decrease}
                    onIncrease={(increase) => onChange({ ...colors, increase })}
                    onDecrease={(decrease) => onChange({ ...colors, decrease })}
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
    const shownByGroup = new Map<
        DisplayOptionGroupKey,
        { definition: DisplayOptionDefinition; item: DisplayOptionItem }[]
    >()
    const countByGroup = new Map<DisplayOptionGroupKey, number>()

    for (const definition of definitions) {
        const name = definition.name as keyof DisplayOptionBindings<C>
        const binding = bindings[name] as AnyBinding<C> | undefined
        if (!binding || !binding.showCondition(c)) {
            continue
        }
        const group = definition.group
        shownByGroup.set(group, [
            ...(shownByGroup.get(group) ?? []),
            { definition, item: { name, element: renderOption(definition, binding, c) } },
        ])
        countByGroup.set(group, (countByGroup.get(group) ?? 0) + Number(binding.changedCount?.(c) ?? 0))
    }

    const groupSections = (group: (typeof DISPLAY_OPTION_GROUPS)[number]): DisplayOptionSection[] => {
        const sections: DisplayOptionSection[] = []
        let run: DisplayOptionItem[] = []
        const flushRun = (): void => {
            if (run.length === 0) {
                return
            }
            const isFirstRun = !sections.some((section) => section.key === group.key)
            sections.push(
                isFirstRun
                    ? {
                          key: group.key,
                          title: overrides[group.key]?.title ?? ('title' in group ? group.title : undefined),
                          dataAttr: 'dataAttr' in group ? group.dataAttr : undefined,
                          items: run,
                      }
                    : { key: `${group.key}-${sections.length}`, items: run }
            )
            run = []
        }
        for (const { definition, item } of shownByGroup.get(group.key) ?? []) {
            if (definition.stacked) {
                flushRun()
                sections.push({
                    key: definition.name,
                    title: definition.label,
                    tooltip: definition.info,
                    items: [item],
                })
            } else {
                run.push(item)
            }
        }
        flushRun()
        return sections
    }

    const allTabs: DisplayOptionTab[] = DISPLAY_OPTION_TABS.map((tab) => {
        const groups = DISPLAY_OPTION_GROUPS.filter((group) => group.tab === tab.key)
        const sections = groups.flatMap(groupSections)
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
