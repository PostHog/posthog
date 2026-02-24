import { LemonInput, LemonInputSelect, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import {
    BooleanVariable,
    DateVariable,
    ListVariable,
    NumberVariable,
    StringVariable,
    Variable,
    VariableType,
} from '../../types'
import { VariableCalendar } from './VariableCalendar'

export const VARIABLE_TYPE_OPTIONS: Array<{ value: VariableType; label: string }> = [
    { value: 'String', label: 'String' },
    { value: 'Number', label: 'Number' },
    { value: 'Boolean', label: 'Boolean' },
    { value: 'List', label: 'List' },
    { value: 'Date', label: 'Date' },
]

export const getCodeName = (name: string): string => {
    return (
        name
            .trim()
            //  Filter out all characters that is not a letter, number or space or underscore
            .replace(/[^a-zA-Z0-9\s_]/g, '')
            .replace(/\s/g, '_')
            .toLowerCase()
    )
}

export const sanitizeCodeName = (name: string): string => {
    return name
        .trim()
        .replace(/[^a-zA-Z0-9\s_]/g, '')
        .replace(/\s/g, '_')
}

export const formatVariableReference = (codeName: string): string => {
    return `{variables.${codeName}}`
}

// Field components for direct prop binding (used in modal)
export interface DirectFieldProps<T extends Variable = Variable> {
    variable: T
    updateVariable: (variable: T) => void
    onSave: () => void
}

export const StringField = ({ variable, updateVariable }: DirectFieldProps<StringVariable>): JSX.Element => (
    <LemonInput
        placeholder="Default value"
        value={variable.default_value}
        onChange={(value) => updateVariable({ ...variable, default_value: value })}
    />
)

export const NumberField = ({ variable, updateVariable }: DirectFieldProps<NumberVariable>): JSX.Element => (
    <LemonInput
        placeholder="Default value"
        type="number"
        value={variable.default_value}
        onChange={(value) => updateVariable({ ...variable, default_value: Number(value ?? 0) })}
    />
)

export const BooleanField = ({ variable, updateVariable }: DirectFieldProps<BooleanVariable>): JSX.Element => (
    <LemonSegmentedButton
        className="w-full"
        value={variable.default_value ? 'true' : 'false'}
        onChange={(value) => updateVariable({ ...variable, default_value: value === 'true' })}
        options={[
            { value: 'true', label: 'true' },
            { value: 'false', label: 'false' },
        ]}
    />
)

export const ListValuesField = ({ variable, updateVariable }: DirectFieldProps<ListVariable>): JSX.Element => (
    <LemonInputSelect
        value={variable.values}
        onChange={(value) => updateVariable({ ...variable, values: value })}
        placeholder="Options..."
        mode="multiple"
        allowCustomValues={true}
        options={[]}
        sortable={true}
    />
)

export const ListDefaultField = ({ variable, updateVariable }: DirectFieldProps<ListVariable>): JSX.Element => (
    <LemonSelect
        className="w-full"
        placeholder="Select default value"
        value={variable.default_value}
        options={variable.values.map((n: string) => ({ label: n, value: n }))}
        onChange={(value) => updateVariable({ ...variable, default_value: value ?? '' })}
        allowClear
        dropdownMaxContentWidth
    />
)

export const DateField = ({ variable, updateVariable, onSave }: DirectFieldProps<DateVariable>): JSX.Element => (
    <VariableCalendar
        value={dayjs(variable.default_value)}
        updateVariable={(date) => {
            updateVariable({ ...variable, default_value: date })
            // calendar is a special case to reuse LemonCalendarSelect
            onSave()
        }}
    />
)

// Helper to narrow variable types based on the type property
function withTypedVariable<T extends Variable>(
    variable: Variable,
    updateVariable: (variable: Variable) => void
): { variable: T; updateVariable: (variable: T) => void } {
    return {
        variable: variable as T,
        updateVariable: updateVariable as (variable: T) => void,
    }
}

export const renderDefaultValueFields = (
    variableType: VariableType,
    variable: Variable,
    updateVariable: (variable: Variable) => void,
    onSave: () => void
): JSX.Element => {
    switch (variableType) {
        case 'String': {
            const props = withTypedVariable<StringVariable>(variable, updateVariable)
            return <StringField {...props} onSave={onSave} />
        }
        case 'Number': {
            const props = withTypedVariable<NumberVariable>(variable, updateVariable)
            return <NumberField {...props} onSave={onSave} />
        }
        case 'Boolean': {
            const props = withTypedVariable<BooleanVariable>(variable, updateVariable)
            return <BooleanField {...props} onSave={onSave} />
        }
        case 'List': {
            const props = withTypedVariable<ListVariable>(variable, updateVariable)
            return (
                <>
                    <ListValuesField {...props} onSave={onSave} />
                    <ListDefaultField {...props} onSave={onSave} />
                </>
            )
        }
        case 'Date': {
            const props = withTypedVariable<DateVariable>(variable, updateVariable)
            return <DateField {...props} onSave={onSave} />
        }
        default:
            throw new Error(`Unsupported variable type: ${variableType}`)
    }
}
