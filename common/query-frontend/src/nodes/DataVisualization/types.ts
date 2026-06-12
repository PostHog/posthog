export type ColumnScalar =
    | 'INTEGER'
    | 'FLOAT'
    | 'DATETIME'
    | 'DATE'
    | 'BOOLEAN'
    | 'DECIMAL'
    | 'STRING'
    | 'TUPLE'
    | 'ARRAY'
    | 'UNKNOWN'

export interface FormattingTemplate {
    id: string
    label: string
    hog: string
    availableColumnTypes: ColumnScalar[]
    hideInput?: boolean
}

export type RuleKeys = 'id' | 'columnName' | 'template' | 'input'

export const FORMATTING_TEMPLATES: FormattingTemplate[] = [
    {
        id: 'equals',
        label: 'Is equal to',
        hog: 'return value == input',
        availableColumnTypes: ['INTEGER', 'FLOAT', 'DATETIME', 'DATE', 'BOOLEAN', 'DECIMAL', 'STRING'],
    },
    {
        id: 'not_equals',
        label: 'Is not equal to',
        hog: 'return value != input',
        availableColumnTypes: ['INTEGER', 'FLOAT', 'DATETIME', 'DATE', 'BOOLEAN', 'DECIMAL', 'STRING'],
    },
    {
        id: 'greater_than',
        label: 'Is greater than',
        hog: 'return value > input',
        availableColumnTypes: ['INTEGER', 'FLOAT', 'DATETIME', 'DATE', 'BOOLEAN', 'DECIMAL'],
    },
    {
        id: 'greater_than_equal',
        label: 'Is greater than or equal to',
        hog: 'return value >= input',
        availableColumnTypes: ['INTEGER', 'FLOAT', 'DATETIME', 'DATE', 'BOOLEAN', 'DECIMAL'],
    },
    {
        id: 'less_than',
        label: 'Is less than',
        hog: 'return value < input',
        availableColumnTypes: ['INTEGER', 'FLOAT', 'DATETIME', 'DATE', 'BOOLEAN', 'DECIMAL'],
    },
    {
        id: 'less_than_equal',
        label: 'Is less than or equal to',
        hog: 'return value <= input',
        availableColumnTypes: ['INTEGER', 'FLOAT', 'DATETIME', 'DATE', 'BOOLEAN', 'DECIMAL'],
    },
    {
        id: 'is_null',
        label: 'Is null',
        hog: 'return value == null',
        availableColumnTypes: ['INTEGER', 'FLOAT', 'DATETIME', 'DATE', 'BOOLEAN', 'DECIMAL', 'STRING'],
        hideInput: true,
    },
    {
        id: 'is_not_null',
        label: 'Is not null',
        hog: 'return value != null',
        availableColumnTypes: ['INTEGER', 'FLOAT', 'DATETIME', 'DATE', 'BOOLEAN', 'DECIMAL', 'STRING'],
        hideInput: true,
    },
]

export type VariableType = 'String' | 'Number' | 'Boolean' | 'List' | 'Date'

interface VariableBase {
    id: string
    name: string
    code_name: string
    type: VariableType
    value?: any
    isNull?: boolean
}

export interface StringVariable extends VariableBase {
    type: 'String'
    default_value: string
    value?: string
}
export interface NumberVariable extends VariableBase {
    type: 'Number'
    default_value: number
    value?: number
}
export interface BooleanVariable extends VariableBase {
    type: 'Boolean'
    default_value: boolean
    value?: boolean
}
export interface ListVariable extends VariableBase {
    type: 'List'
    values: string[]
    default_value: string
    value?: string
}

export interface DateVariable extends VariableBase {
    type: 'Date'
    default_value: string
    value?: string
}

export type Variable = StringVariable | NumberVariable | BooleanVariable | ListVariable | DateVariable
