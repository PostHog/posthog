import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'
import { uuid } from 'lib/utils'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { QuickFilterContext } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator, QuickFilter, QuickFilterOption } from '~/types'

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
    options: QuickFilterOption[]
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

export const quickFilterFormLogic = kea<quickFilterFormLogicType>([
    path(['lib', 'components', 'QuickFilters', 'quickFilterFormLogic']),
    props({} as QuickFilterFormLogicProps),
    key((props) => `${props.context}-${props.filter?.id || 'new'}`),

    connect((props: QuickFilterFormLogicProps) => ({
        values: [propertyDefinitionsModel, ['options as propertyOptions']],
        actions: [propertyDefinitionsModel, ['loadPropertyValues'], quickFiltersModalLogic(props), ['closeModal']],
    })),

    actions({
        setName: (name: string) => ({ name }),
        setPropertyName: (propertyName: string) => ({ propertyName }),
        addOption: true,
        removeOption: (index: number) => ({ index }),
        updateOption: (index: number, updates: Partial<QuickFilterOption>) => ({ index, updates }),
        submitForm: true,
        loadPropertySuggestions: (propertyName: string, searchInput?: string) => ({ propertyName, searchInput }),
    }),

    reducers(({ props }) => ({
        name: [
            props.filter?.name || '',
            {
                setName: (_, { name }) => name,
            },
        ],
        propertyName: [
            props.filter?.property_name || '',
            {
                setPropertyName: (_, { propertyName }) => propertyName,
            },
        ],
        options: [
            (props.filter?.options || [
                { id: uuid(), value: null, label: '', operator: PropertyOperator.Exact },
            ]) as QuickFilterOption[],
            {
                addOption: (state) => [
                    ...state,
                    { id: uuid(), value: null, label: '', operator: PropertyOperator.Exact },
                ],
                removeOption: (state, { index }) => state.filter((_, i) => i !== index),
                updateOption: (state, { index, updates }) => {
                    const newOptions = [...state]
                    newOptions[index] = { ...newOptions[index], ...updates }
                    return newOptions
                },
            },
        ],
    })),

    selectors({
        isValid: [
            (s) => [s.name, s.propertyName, s.options],
            (name, propertyName, options): boolean => {
                if (!name.trim() || !propertyName.trim() || options.length === 0) {
                    return false
                }

                return options.every((opt: QuickFilterOption) => {
                    if (!opt.label.trim()) {
                        return false
                    }

                    const operatorNeedsValue = !operatorsWithoutValues.includes(opt.operator as PropertyOperator)
                    if (operatorNeedsValue) {
                        if (opt.value === null) {
                            return false
                        }
                        if (Array.isArray(opt.value)) {
                            return opt.value.length > 0 && opt.value.every((v) => v.trim() !== '')
                        }
                        return opt.value.trim() !== ''
                    }

                    return true
                })
            },
        ],
        suggestions: [
            (s) => [s.propertyName, s.propertyOptions],
            (propertyName, propertyOptions): any[] => {
                return propertyName ? propertyOptions[propertyName]?.values || [] : []
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        updateOption: ({ index, updates }) => {
            if (updates.value !== undefined) {
                const currentOption = values.options[index]
                if (currentOption && !currentOption.label) {
                    const autoLabel = Array.isArray(updates.value) ? updates.value.join(', ') : (updates.value ?? '')
                    if (autoLabel) {
                        actions.updateOption(index, { label: autoLabel })
                    }
                }
            }
        },
        setPropertyName: ({ propertyName }) => {
            if (propertyName) {
                actions.loadPropertySuggestions(propertyName, '')
            }
        },
        loadPropertySuggestions: ({ propertyName, searchInput }) => {
            if (propertyName) {
                actions.loadPropertyValues({
                    endpoint: undefined,
                    type: propertyFilterTypeToPropertyDefinitionType(PropertyFilterType.Event),
                    newInput: searchInput || '',
                    propertyKey: propertyName,
                    eventNames: [],
                    properties: [],
                })
            }
        },
        submitForm: async () => {
            if (!values.isValid) {
                return
            }

            const payload = {
                name: values.name.trim(),
                property_name: values.propertyName.trim(),
                type: 'manual-options' as const,
                options: values.options.map((opt: QuickFilterOption) => ({
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

            actions.closeModal()
        },
    })),
])
