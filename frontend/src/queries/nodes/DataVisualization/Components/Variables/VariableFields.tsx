import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSelect,
    LemonSwitch,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'

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
import {
    RelativeDateUnit,
    formatRelativeDateValue,
    getListVariableSelectedValues,
    getListVariableValues,
    isRelativeDateValue,
    parseRelativeDateValue,
} from './variableUtils'
import { variableValuesLogic } from './variableValuesLogic'

export { coerceListVariableValue, getListVariableValues } from './variableUtils'

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
        value={getListVariableValues(variable)}
        onChange={(value) => updateVariable({ ...variable, values: value })}
        placeholder="Options..."
        mode="multiple"
        allowCustomValues={true}
        options={[]}
        sortable={true}
    />
)

interface ListVariableSelectProps {
    variable: ListVariable
    logicKey: string
    disabledReason?: string | false
    loadOnMount?: boolean
    onChange: (value: string | string[]) => void
    selectedValues?: string[]
    size?: 'small' | 'medium'
}

export const ListVariableSelect = ({
    variable,
    logicKey,
    disabledReason,
    loadOnMount = true,
    onChange,
    selectedValues = getListVariableSelectedValues(variable),
    size,
}: ListVariableSelectProps): JSX.Element => {
    const logic = variableValuesLogic({ key: logicKey, variable, loadOnMount })
    const { loadVariableOptions } = useActions(logic)
    const { requestedValuesQuery, variableOptions, variableOptionsError, variableOptionsLoading } = useValues(logic)
    const valuesQuery = variable.values_query?.trim() ?? null
    const isCurrentQuery = requestedValuesQuery === valuesQuery
    const options =
        variable.values_query == null ? getListVariableValues(variable) : isCurrentQuery ? variableOptions : []
    const currentError = isCurrentQuery ? variableOptionsError : null

    return (
        <LemonInputSelect
            className="w-full"
            mode={variable.is_multi ? 'multiple' : 'single'}
            value={selectedValues}
            options={options.map((value) => ({ key: value, label: value }))}
            onChange={(values) => onChange(variable.is_multi ? values : (values[0] ?? ''))}
            placeholder={variableOptionsLoading ? 'Loading options...' : 'Select a value'}
            emptyStateComponent={currentError ? "Couldn't load options. Check the query, then try again." : undefined}
            status={currentError ? 'danger' : 'default'}
            loading={variableOptionsLoading}
            disabledReason={disabledReason || undefined}
            size={size}
            displayMode={variable.is_multi ? 'count' : 'snacks'}
            bulkActions={variable.is_multi ? 'select-and-clear-all' : undefined}
            action={
                variable.values_query?.trim()
                    ? {
                          children: 'Reload options',
                          onClick: () => loadVariableOptions(variable),
                          loading: variableOptionsLoading,
                      }
                    : undefined
            }
            fullWidth
        />
    )
}

export const ListVariableFields = ({ variable, updateVariable }: DirectFieldProps<ListVariable>): JSX.Element => {
    const isQueryBacked = variable.values_query != null
    const logic = variableValuesLogic({
        key: `variable-form-${variable.id || 'new'}`,
        variable,
        loadOnMount: isQueryBacked && Boolean(variable.values_query?.trim()),
    })
    const { loadVariableOptions } = useActions(logic)
    const { requestedValuesQuery, variableOptions, variableOptionsError, variableOptionsLoading } = useValues(logic)
    const valuesQuery = variable.values_query?.trim() ?? null
    const isCurrentQuery = requestedValuesQuery === valuesQuery
    const availableValues = isQueryBacked ? (isCurrentQuery ? variableOptions : []) : getListVariableValues(variable)
    const currentError = isCurrentQuery ? variableOptionsError : null
    const defaultValues = getListVariableSelectedValues({ ...variable, value: undefined })

    return (
        <>
            <LemonField.Pure label="Options source" className="gap-1">
                <LemonSegmentedButton
                    className="w-full"
                    value={isQueryBacked ? 'query' : 'static'}
                    onChange={(source) => updateVariable({ ...variable, values_query: source === 'query' ? '' : null })}
                    options={[
                        { value: 'static', label: 'Static options' },
                        { value: 'query', label: 'HogQL query' },
                    ]}
                />
            </LemonField.Pure>
            {isQueryBacked ? (
                <LemonField.Pure label="Options query" className="gap-1">
                    <LemonTextArea
                        className="font-mono"
                        value={variable.values_query ?? ''}
                        onChange={(value) => updateVariable({ ...variable, values_query: value })}
                        placeholder={'SELECT DISTINCT event\nFROM events\nLIMIT 100'}
                        minRows={4}
                    />
                    <div className="flex items-center justify-between gap-2 text-xs text-secondary">
                        <span>The first result column becomes the available options.</span>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            onClick={() => loadVariableOptions(variable)}
                            loading={variableOptionsLoading}
                            disabledReason={!variable.values_query?.trim() ? 'Enter a query first' : undefined}
                        >
                            Preview options
                        </LemonButton>
                    </div>
                    {currentError ? (
                        <span className="text-danger text-xs">
                            Couldn't load options. Check the query, then try again.
                        </span>
                    ) : variableOptions.length > 0 ? (
                        <span className="text-success text-xs">
                            Loaded {variableOptions.length} option{variableOptions.length === 1 ? '' : 's'}
                        </span>
                    ) : null}
                </LemonField.Pure>
            ) : (
                <LemonField.Pure label="Options" className="gap-1">
                    <ListValuesField variable={variable} updateVariable={updateVariable} onSave={() => {}} />
                </LemonField.Pure>
            )}
            <LemonSwitch
                label="Allow multiple selections"
                checked={Boolean(variable.is_multi)}
                onChange={(isMulti) => {
                    const normalizedDefault = isMulti ? defaultValues : (defaultValues[0] ?? '')
                    updateVariable({ ...variable, is_multi: isMulti, default_value: normalizedDefault })
                }}
                bordered
            />
            <LemonField.Pure label="Default value" className="gap-1">
                <LemonInputSelect
                    className="w-full"
                    mode={variable.is_multi ? 'multiple' : 'single'}
                    value={defaultValues}
                    options={availableValues.map((value) => ({ key: value, label: value }))}
                    onChange={(values) =>
                        updateVariable({
                            ...variable,
                            default_value: variable.is_multi ? values : (values[0] ?? ''),
                        })
                    }
                    placeholder={variableOptionsLoading ? 'Loading options...' : 'Select a default value'}
                    loading={variableOptionsLoading}
                    emptyStateComponent={isQueryBacked ? 'Preview the query to load options.' : undefined}
                    fullWidth
                />
            </LemonField.Pure>
        </>
    )
}

const RELATIVE_DATE_UNITS: Array<{ value: RelativeDateUnit; label: string }> = [
    { value: 'h', label: 'hours' },
    { value: 'd', label: 'days' },
    { value: 'w', label: 'weeks' },
    { value: 'm', label: 'months' },
    { value: 'y', label: 'years' },
]

export const DateField = ({ variable, updateVariable }: DirectFieldProps<DateVariable>): JSX.Element => {
    const isRelative = isRelativeDateValue(variable.default_value)
    const relativeValue = parseRelativeDateValue(variable.default_value) ?? { amount: 0, unit: 'd' as RelativeDateUnit }

    return (
        <div className="flex flex-col gap-2">
            <LemonSegmentedButton
                className="w-full"
                value={isRelative ? 'relative' : 'fixed'}
                onChange={(mode) =>
                    updateVariable({
                        ...variable,
                        default_value: mode === 'relative' ? '-0d' : dayjs().format('YYYY-MM-DD HH:mm:00'),
                    })
                }
                options={[
                    { value: 'fixed', label: 'Fixed date' },
                    { value: 'relative', label: 'Relative date' },
                ]}
            />
            {isRelative ? (
                <div className="flex items-center gap-2">
                    <LemonInput
                        type="number"
                        min={0}
                        value={relativeValue.amount}
                        onChange={(amount) =>
                            updateVariable({
                                ...variable,
                                default_value: `-${Math.max(0, Number(amount ?? 0))}${relativeValue.unit}`,
                            })
                        }
                    />
                    <LemonSelect<RelativeDateUnit>
                        className="grow"
                        value={relativeValue.unit}
                        options={RELATIVE_DATE_UNITS}
                        onChange={(unit) =>
                            updateVariable({
                                ...variable,
                                default_value: `-${relativeValue.amount}${unit ?? 'd'}`,
                            })
                        }
                    />
                    <span className="whitespace-nowrap text-secondary">ago</span>
                </div>
            ) : (
                <VariableCalendar
                    value={dayjs(variable.default_value)}
                    rawValue={variable.default_value}
                    updateVariable={(date) => updateVariable({ ...variable, default_value: date })}
                />
            )}
            {isRelative && (
                <span className="text-xs text-secondary">
                    Current value: {formatRelativeDateValue(variable.default_value)}
                </span>
            )}
        </div>
    )
}

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
            return <ListVariableFields {...props} onSave={onSave} />
        }
        case 'Date': {
            const props = withTypedVariable<DateVariable>(variable, updateVariable)
            return <DateField {...props} onSave={onSave} />
        }
        default:
            throw new Error(`Unsupported variable type: ${variableType}`)
    }
}
