import { LemonInput, LemonInputSelect, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { Variable, VariableType } from '../../types'
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

export const formatVariableReference = (codeName: string): string => {
    return `{variables.${codeName}}`
}

// Field components for direct prop binding (used in modal)
export interface DirectFieldProps {
    variable: Variable
    updateVariable: (variable: Variable) => void
    onSave: () => void
}

export const StringField = ({ variable, updateVariable }: DirectFieldProps): JSX.Element => (
    <LemonInput
        placeholder="Default value"
        value={variable.default_value}
        onChange={(value) => updateVariable({ ...variable, default_value: value })}
    />
)

export const NumberField = ({ variable, updateVariable }: DirectFieldProps): JSX.Element => (
    <LemonInput
        placeholder="Default value"
        type="number"
        value={variable.default_value}
        onChange={(value) => updateVariable({ ...variable, default_value: value ?? 0 })}
    />
)

export const BooleanField = ({ variable, updateVariable }: DirectFieldProps): JSX.Element => (
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

export const ListValuesField = ({ variable, updateVariable }: DirectFieldProps): JSX.Element => (
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

export const ListDefaultField = ({ variable, updateVariable }: DirectFieldProps): JSX.Element => (
    <LemonSelect
        className="w-full"
        placeholder="Select default value"
        value={variable.default_value}
        options={variable.values.map((n) => ({ label: n, value: n }))}
        onChange={(value) => updateVariable({ ...variable, default_value: value ?? '' })}
        allowClear
        dropdownMaxContentWidth
    />
)

export const DateField = ({ variable, updateVariable, onSave }: DirectFieldProps): JSX.Element => (
    <VariableCalendar
        value={dayjs(variable.default_value)}
        updateVariable={(date) => {
            updateVariable({ ...variable, default_value: date })
            // calendar is a special case to reuse LemonCalendarSelect
            onSave()
        }}
    />
)

export const renderDefaultValueFields = (
    variableType: VariableType,
    variable: Variable,
    updateVariable: (variable: Variable) => void,
    onSave: () => void
): JSX.Element => {
    const props: DirectFieldProps = { variable, updateVariable, onSave }

    switch (variableType) {
        case 'String':
            return <StringField {...props} />
        case 'Number':
            return <NumberField {...props} />
        case 'Boolean':
            return <BooleanField {...props} />
        case 'List':
            return (
                <>
                    <ListValuesField {...props} />
                    <ListDefaultField {...props} />
                </>
            )
        case 'Date':
            return <DateField {...props} />
        default:
            throw new Error(`Unsupported variable type: ${variableType}`)
    }
}
