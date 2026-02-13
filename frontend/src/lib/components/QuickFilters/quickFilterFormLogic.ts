import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'

import { propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'
import { uuid } from 'lib/utils'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { QuickFilterContext, QuickFilterType } from '~/queries/schema/schema-general'
import {
    PropertyFilterType,
    PropertyOperator,
    QuickFilter,
    QuickFilterAutoDiscoveryConfig,
    QuickFilterOption,
    isAutoDiscoveryQuickFilter,
} from '~/types'

import type { quickFilterFormLogicType } from './quickFilterFormLogicType'
import { quickFiltersLogic } from './quickFiltersLogic'
import { quickFiltersModalLogic } from './quickFiltersModalLogic'

export interface QuickFilterFormLogicProps {
    filter: QuickFilter | null
    context: QuickFilterContext
}

export interface QuickFilterFormValues {
    name: string
    propertyName: string
    filterType: QuickFilterType
    // Manual mode fields
    options: QuickFilterOption[]
    // Auto-discovery mode fields
    regexPattern: string
    operator: PropertyOperator
}

export const allowedOperators = [
    PropertyOperator.Exact,
    PropertyOperator.IsNot,
    PropertyOperator.IContains,
    PropertyOperator.NotIContains,
    PropertyOperator.Regex,
    PropertyOperator.IsSet,
    PropertyOperator.IsNotSet,
]

const trimValue = (value: string | string[] | null): string | string[] | null => {
    if (value === null) {
        return null
    }
    if (Array.isArray(value)) {
        return value.map((v) => v.trim())
    }
    return value.trim()
}

export const operatorsWithoutValues = [PropertyOperator.IsSet, PropertyOperator.IsNotSet]

function getAutoDiscoveryDefaults(filter: QuickFilter | null): {
    regexPattern: string
    operator: PropertyOperator
} {
    if (filter && isAutoDiscoveryQuickFilter(filter)) {
        const config = filter.options
        return {
            regexPattern: config.regex_pattern || '',
            operator: (config.operator as PropertyOperator) || PropertyOperator.Exact,
        }
    }
    return { regexPattern: '', operator: PropertyOperator.Exact }
}

function getManualOptionsDefaults(filter: QuickFilter | null): QuickFilterOption[] {
    if (filter && !isAutoDiscoveryQuickFilter(filter)) {
        return filter.options as QuickFilterOption[]
    }
    return [{ id: uuid(), value: null, label: '', operator: PropertyOperator.Exact }]
}

export const quickFilterFormLogic = kea<quickFilterFormLogicType>([
    path(['lib', 'components', 'QuickFilters', 'quickFilterFormLogic']),
    props({} as QuickFilterFormLogicProps),
    key((props) => `${props.context}-${props.filter?.id || 'new'}`),

    connect((props: QuickFilterFormLogicProps) => ({
        values: [propertyDefinitionsModel, ['options as propertyOptions']],
        actions: [propertyDefinitionsModel, ['loadPropertyValues'], quickFiltersModalLogic(props), ['closeModal']],
    })),

    actions({
        addOption: true,
        removeOption: (index: number) => ({ index }),
        updateOption: (index: number, updates: Partial<QuickFilterOption>) => ({ index, updates }),
    }),

    forms(({ actions, props }) => ({
        quickFilter: {
            defaults: {
                name: props.filter?.name || '',
                propertyName: props.filter?.property_name || '',
                filterType: props.filter?.type || 'manual-options',
                options: getManualOptionsDefaults(props.filter),
                ...getAutoDiscoveryDefaults(props.filter),
            } as QuickFilterFormValues,
            errors: ({ name, propertyName, filterType, options, regexPattern }) => {
                const errors: Record<string, string | object | undefined> = {}

                if (!name.trim()) {
                    errors.name = 'Filter name is required'
                }

                if (!propertyName.trim()) {
                    errors.propertyName = 'Event property is required'
                }

                if (filterType === 'auto-discovery') {
                    if (regexPattern.trim()) {
                        try {
                            new RegExp(regexPattern)
                        } catch {
                            errors.regexPattern = 'Invalid regex pattern'
                        }
                    }
                } else {
                    if (options.length === 0) {
                        errors.options = 'At least one option is required'
                    } else {
                        const optionErrors: Record<string, string>[] = []
                        let hasOptionErrors = false

                        options.forEach((opt: QuickFilterOption, index: number) => {
                            const optError: Record<string, string> = {}

                            if (!opt.label.trim()) {
                                optError.label = 'Display name is required'
                                hasOptionErrors = true
                            }

                            const operatorNeedsValue = !operatorsWithoutValues.includes(
                                opt.operator as PropertyOperator
                            )
                            if (operatorNeedsValue) {
                                if (!opt.value || (Array.isArray(opt.value) && opt.value.length === 0)) {
                                    optError.value = 'Value is required'
                                    hasOptionErrors = true
                                }
                            }

                            optionErrors[index] = optError
                        })

                        if (hasOptionErrors) {
                            errors.options = optionErrors
                        }
                    }
                }

                return errors
            },
            submit: async ({ name, propertyName, filterType, options, regexPattern, operator }) => {
                if (filterType === 'auto-discovery') {
                    const payload = {
                        name: name.trim(),
                        property_name: propertyName.trim(),
                        type: 'auto-discovery' as const,
                        options: {
                            operator,
                            regex_pattern: regexPattern.trim() || null,
                        } as QuickFilterAutoDiscoveryConfig,
                    }

                    if (props.filter) {
                        await quickFiltersLogic(props).asyncActions.updateFilter(props.filter.id, payload)
                    } else {
                        await quickFiltersLogic(props).asyncActions.createFilter(payload)
                    }
                } else {
                    const payload = {
                        name: name.trim(),
                        property_name: propertyName.trim(),
                        type: 'manual-options' as const,
                        options: options.map((opt: QuickFilterOption) => ({
                            id: opt.id,
                            value: trimValue(opt.value),
                            label: opt.label.trim(),
                            operator: opt.operator || PropertyOperator.Exact,
                        })),
                    }

                    if (props.filter) {
                        await quickFiltersLogic(props).asyncActions.updateFilter(props.filter.id, payload)
                    } else {
                        await quickFiltersLogic(props).asyncActions.createFilter(payload)
                    }
                }

                actions.closeModal()
            },
        },
    })),

    selectors({
        name: [(s) => [s.quickFilter], (quickFilter) => quickFilter.name],
        propertyName: [(s) => [s.quickFilter], (quickFilter) => quickFilter.propertyName],
        filterType: [(s) => [s.quickFilter], (quickFilter) => quickFilter.filterType],
        options: [(s) => [s.quickFilter], (quickFilter) => quickFilter.options],
        regexPattern: [(s) => [s.quickFilter], (quickFilter) => quickFilter.regexPattern],
        operator: [(s) => [s.quickFilter], (quickFilter) => quickFilter.operator],
        suggestions: [
            (s) => [s.propertyName, s.propertyOptions],
            (propertyName, propertyOptions): any[] => {
                return propertyName ? propertyOptions[propertyName]?.values || [] : []
            },
        ],
        filteredSuggestions: [
            (s) => [s.suggestions, s.regexPattern],
            (suggestions, regexPattern): any[] => {
                if (!regexPattern?.trim()) {
                    return suggestions
                }
                try {
                    const regex = new RegExp(regexPattern)
                    return suggestions.filter((s: any) => regex.test(String(s.name ?? '')))
                } catch {
                    return suggestions
                }
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setQuickFilterValue: ({ name, value }) => {
            if (name === 'propertyName' && value) {
                actions.loadPropertyValues({
                    endpoint: undefined,
                    type: propertyFilterTypeToPropertyDefinitionType(PropertyFilterType.Event),
                    newInput: '',
                    propertyKey: value as string,
                    eventNames: [],
                    properties: [],
                })
            }

            // Auto-fill label when value is set and label is empty
            if (Array.isArray(name) && name[0] === 'options' && name[2] === 'value') {
                const optionIndex = name[1] as number
                const currentOption = values.options[optionIndex]
                if (currentOption && !currentOption.label) {
                    const autoLabel = Array.isArray(value) ? (value as string[]).join(', ') : ((value as string) ?? '')
                    if (autoLabel) {
                        actions.setQuickFilterValue(['options', optionIndex, 'label'], autoLabel)
                    }
                }
            }
        },
        addOption: () => {
            actions.setQuickFilterValue('options', [
                ...values.options,
                { id: uuid(), value: null, label: '', operator: PropertyOperator.Exact },
            ])
        },
        removeOption: ({ index }) => {
            actions.setQuickFilterValue(
                'options',
                values.options.filter((_, i) => i !== index)
            )
        },
        updateOption: ({ index, updates }) => {
            for (const [key, value] of Object.entries(updates)) {
                actions.setQuickFilterValue(['options', index, key], value)
            }
        },
    })),
])
