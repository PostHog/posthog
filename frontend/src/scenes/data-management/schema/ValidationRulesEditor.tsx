import { LemonInput, LemonInputSelect, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import {
    NumericRangeRules,
    SchemaPropertyGroupProperty,
    StringEnumRules,
    StringNotEnumRules,
    StringValidationRules,
    ValidationRules,
} from './schemaManagementLogic'

type StringMode = 'allow' | 'deny'

function getStringMode(rules: StringValidationRules): StringMode {
    return 'not' in rules ? 'deny' : 'allow'
}

function getStringValues(rules: StringValidationRules): string[] {
    if ('not' in rules) {
        return (rules as StringNotEnumRules).not.enum
    }
    return (rules as StringEnumRules).enum
}

function buildStringRules(mode: StringMode, values: string[]): StringValidationRules {
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
    const mode = rules ? getStringMode(rules) : 'allow'
    const values = rules ? getStringValues(rules) : []

    return (
        <div className="flex flex-col gap-2 p-3">
            <div className="flex items-center gap-2">
                <span className="text-sm font-medium whitespace-nowrap">Value list:</span>
                <LemonSegmentedButton
                    value={mode}
                    onChange={(newMode) => {
                        onChange(values.length > 0 ? buildStringRules(newMode, values) : null)
                    }}
                    options={[
                        { value: 'allow' as StringMode, label: 'Allow list' },
                        { value: 'deny' as StringMode, label: 'Deny list' },
                    ]}
                    size="small"
                />
            </div>
            <LemonInputSelect
                mode="multiple"
                placeholder="Type a value and press Enter"
                options={values.map((v) => ({ key: v, label: v }))}
                value={values}
                onChange={(newValues) => {
                    onChange(newValues.length > 0 ? buildStringRules(mode, newValues) : null)
                }}
                allowCustomValues
            />
        </div>
    )
}

type BoundType = 'inclusive' | 'exclusive'

interface NumericBoundRowProps {
    label: string
    value: number | undefined
    boundType: BoundType
    onValueChange: (value: number | undefined) => void
    onBoundTypeChange: (boundType: BoundType) => void
}

function NumericBoundRow({
    label,
    value,
    boundType,
    onValueChange,
    onBoundTypeChange,
}: NumericBoundRowProps): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <span className="text-sm font-medium w-16">{label}</span>
            <LemonInput
                type="number"
                value={value}
                onChange={(val) => {
                    onValueChange(val)
                }}
                placeholder="No limit"
                className="w-32"
                size="small"
            />
            <LemonSelect
                value={boundType}
                onChange={onBoundTypeChange}
                options={[
                    { value: 'inclusive' as BoundType, label: 'Inclusive' },
                    { value: 'exclusive' as BoundType, label: 'Exclusive' },
                ]}
                size="small"
            />
        </div>
    )
}

interface NumericValidationEditorProps {
    rules: NumericRangeRules | null
    onChange: (rules: ValidationRules | null) => void
}

function NumericValidationEditor({ rules, onChange }: NumericValidationEditorProps): JSX.Element {
    const lowerValue = rules?.minimum ?? rules?.exclusiveMinimum
    const upperValue = rules?.maximum ?? rules?.exclusiveMaximum
    const lowerType: BoundType = rules?.exclusiveMinimum !== undefined ? 'exclusive' : 'inclusive'
    const upperType: BoundType = rules?.exclusiveMaximum !== undefined ? 'exclusive' : 'inclusive'

    const buildRules = (
        lower: number | undefined,
        lType: BoundType,
        upper: number | undefined,
        uType: BoundType
    ): NumericRangeRules | null => {
        if (lower === undefined && upper === undefined) {
            return null
        }
        const result: NumericRangeRules = {}
        if (lower !== undefined) {
            if (lType === 'exclusive') {
                result.exclusiveMinimum = lower
            } else {
                result.minimum = lower
            }
        }
        if (upper !== undefined) {
            if (uType === 'exclusive') {
                result.exclusiveMaximum = upper
            } else {
                result.maximum = upper
            }
        }
        return result
    }

    return (
        <div className="flex flex-col gap-2 p-3">
            <NumericBoundRow
                label="Min"
                value={lowerValue}
                boundType={lowerType}
                onValueChange={(val) => onChange(buildRules(val, lowerType, upperValue, upperType))}
                onBoundTypeChange={(bt) => onChange(buildRules(lowerValue, bt, upperValue, upperType))}
            />
            <NumericBoundRow
                label="Max"
                value={upperValue}
                boundType={upperType}
                onValueChange={(val) => onChange(buildRules(lowerValue, lowerType, val, upperType))}
                onBoundTypeChange={(bt) => onChange(buildRules(lowerValue, lowerType, upperValue, bt))}
            />
        </div>
    )
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
            onChange={handleChange}
        />
    )
}
