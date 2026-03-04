import { useRef } from 'react'

import { LemonInput, LemonInputSelect, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import {
    NumericRangeRules,
    SchemaPropertyGroupProperty,
    StringEnumRules,
    StringNotEnumRules,
    StringValidationRules,
    ValidationRules,
} from './schemaManagementLogic'

type StringMode = 'none' | 'allow' | 'deny'

function getStringMode(rules: StringValidationRules | null): StringMode {
    if (!rules) {
        return 'none'
    }
    return 'not' in rules ? 'deny' : 'allow'
}

function getStringValues(rules: StringValidationRules): string[] {
    if ('not' in rules) {
        return (rules as StringNotEnumRules).not.enum
    }
    return (rules as StringEnumRules).enum
}

function buildStringRules(mode: StringMode, values: string[]): StringValidationRules | null {
    if (mode === 'none') {
        return null
    }
    if (mode === 'deny') {
        return { not: { enum: values } }
    }
    return { enum: values }
}

interface StringValidationEditorProps {
    rules: StringValidationRules | null
    onChange: (rules: ValidationRules | null) => void
}

function StringValidationEditor({ rules, onChange }: StringValidationEditorProps): JSX.Element {
    const mode = getStringMode(rules)
    const values = rules ? getStringValues(rules) : []
    const cachedValues = useRef<string[]>(values)

    if (values.length > 0) {
        cachedValues.current = values
    }

    return (
        <div className="flex flex-col gap-2 p-3">
            <div className="flex items-center gap-2">
                <span className="text-sm font-medium whitespace-nowrap">Values:</span>
                <LemonSegmentedButton
                    value={mode}
                    onChange={(newMode) => {
                        const restored = newMode !== 'none' ? cachedValues.current : []
                        onChange(buildStringRules(newMode, restored))
                    }}
                    options={[
                        { value: 'none' as StringMode, label: 'No filtering' },
                        { value: 'allow' as StringMode, label: 'Allow list' },
                        { value: 'deny' as StringMode, label: 'Deny list' },
                    ]}
                    size="small"
                />
            </div>
            {mode !== 'none' && (
                <LemonInputSelect
                    mode="multiple"
                    placeholder="Type a value and press Enter"
                    options={values.map((v) => ({ key: v, label: v }))}
                    value={values}
                    onChange={(newValues) => {
                        cachedValues.current = newValues
                        onChange(buildStringRules(mode, newValues))
                    }}
                    allowCustomValues
                />
            )}
        </div>
    )
}

type ComparisonOp = '<' | '<='

interface NumericValidationEditorProps {
    rules: NumericRangeRules | null
    propertyName: string
    onChange: (rules: ValidationRules | null) => void
}

type NumericMode = 'none' | 'range'

function NumericValidationEditor({ rules, propertyName, onChange }: NumericValidationEditorProps): JSX.Element {
    const mode: NumericMode = rules !== null && rules !== undefined ? 'range' : 'none'
    const lowerValue = rules?.minimum ?? rules?.exclusiveMinimum
    const upperValue = rules?.maximum ?? rules?.exclusiveMaximum
    const lowerOp: ComparisonOp = rules?.exclusiveMinimum !== undefined ? '<' : '<='
    const upperOp: ComparisonOp = rules?.exclusiveMaximum !== undefined ? '<' : '<='

    const isNum = (v: number | undefined | null): v is number => typeof v === 'number' && isFinite(v)

    const buildRules = (
        lower: number | undefined | null,
        lOp: ComparisonOp,
        upper: number | undefined | null,
        uOp: ComparisonOp
    ): NumericRangeRules | null => {
        if (!isNum(lower) && !isNum(upper)) {
            return mode === 'range' ? {} : null
        }
        const result: NumericRangeRules = {}
        if (isNum(lower)) {
            if (lOp === '<') {
                result.exclusiveMinimum = lower
            } else {
                result.minimum = lower
            }
        }
        if (isNum(upper)) {
            if (uOp === '<') {
                result.exclusiveMaximum = upper
            } else {
                result.maximum = upper
            }
        }
        return result
    }

    return (
        <div className="flex flex-col gap-2 p-3">
            <div className="flex items-center gap-2">
                <span className="text-sm font-medium whitespace-nowrap">Range:</span>
                <LemonSegmentedButton
                    value={mode}
                    onChange={(newMode) => {
                        if (newMode === 'none') {
                            onChange(null)
                        } else {
                            onChange(rules ?? {})
                        }
                    }}
                    options={[
                        { value: 'none' as NumericMode, label: 'No filtering' },
                        { value: 'range' as NumericMode, label: 'Range' },
                    ]}
                    size="small"
                />
            </div>
            {mode === 'range' && (
                <div className="flex items-center gap-2">
                    <LemonInput
                        type="number"
                        value={lowerValue}
                        onChange={(val) => onChange(buildRules(val, lowerOp, upperValue, upperOp))}
                        placeholder="No limit"
                        className="w-28"
                        size="small"
                    />
                    <LemonSelect
                        value={lowerOp}
                        onChange={(op) => onChange(buildRules(lowerValue, op, upperValue, upperOp))}
                        options={[
                            { value: '<=' as ComparisonOp, label: '≤' },
                            { value: '<' as ComparisonOp, label: '<' },
                        ]}
                        size="small"
                    />
                    <span className="text-sm font-medium whitespace-nowrap">{propertyName || 'value'}</span>
                    <LemonSelect
                        value={upperOp}
                        onChange={(op) => onChange(buildRules(lowerValue, lowerOp, upperValue, op))}
                        options={[
                            { value: '<=' as ComparisonOp, label: '≤' },
                            { value: '<' as ComparisonOp, label: '<' },
                        ]}
                        size="small"
                    />
                    <LemonInput
                        type="number"
                        value={upperValue}
                        onChange={(val) => onChange(buildRules(lowerValue, lowerOp, val, upperOp))}
                        placeholder="No limit"
                        className="w-28"
                        size="small"
                    />
                </div>
            )}
        </div>
    )
}

export function validationRulesSummary(property: SchemaPropertyGroupProperty): string | null {
    const rules = property.validation_rules
    if (!rules || (typeof rules === 'object' && Object.keys(rules).length === 0)) {
        return null
    }

    if (property.property_type === 'String') {
        if ('not' in rules) {
            const count = (rules as StringNotEnumRules).not.enum.length
            return count > 0 ? `Deny ${count} value${count === 1 ? '' : 's'}` : null
        }
        if ('enum' in rules) {
            const count = (rules as StringEnumRules).enum.length
            return count > 0 ? `Allow ${count} value${count === 1 ? '' : 's'}` : null
        }
    }

    if (property.property_type === 'Numeric') {
        const r = rules as NumericRangeRules
        const lower = r.minimum ?? r.exclusiveMinimum
        const upper = r.maximum ?? r.exclusiveMaximum
        const lowerOp = r.exclusiveMinimum !== undefined ? '<' : '≤'
        const upperOp = r.exclusiveMaximum !== undefined ? '<' : '≤'
        if (lower !== undefined && upper !== undefined) {
            return `${lower} ${lowerOp} x ${upperOp} ${upper}`
        }
        if (lower !== undefined) {
            return `${lower} ${lowerOp} x`
        }
        if (upper !== undefined) {
            return `x ${upperOp} ${upper}`
        }
    }

    return null
}

interface ValidationRulesEditorProps {
    property: SchemaPropertyGroupProperty
    index: number
    onUpdate: (index: number, updates: Partial<SchemaPropertyGroupProperty>) => void
}

export function ValidationRulesEditor({ property, index, onUpdate }: ValidationRulesEditorProps): JSX.Element {
    const handleChange = (rules: ValidationRules | null): void => {
        onUpdate(index, { validation_rules: rules })
    }

    if (property.property_type === 'String') {
        return (
            <StringValidationEditor
                rules={property.validation_rules as StringValidationRules | null}
                onChange={handleChange}
            />
        )
    }

    return (
        <NumericValidationEditor
            rules={property.validation_rules as NumericRangeRules | null}
            propertyName={property.name}
            onChange={handleChange}
        />
    )
}
