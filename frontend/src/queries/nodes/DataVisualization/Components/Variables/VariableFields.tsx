import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSelect,
    LemonSwitch,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import {
    POSTHOG_WAREHOUSE,
    connectionSelectorLogic,
    getConnectionOptionLabel,
} from 'scenes/data-warehouse/editor/connectionSelectorLogic'

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
    normalizeRelativeDateAmount,
    parseRelativeDateValue,
} from './variableUtils'
import { getStaticVariableOptions, getValuesQueryKey, variableValuesLogic } from './variableValuesLogic'

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
    disabledReason?: string | false
    loadOnMount?: boolean
    onBlur?: () => void
    onChange: (value: string | string[]) => void
    selectedValues?: string[]
    size?: 'small' | 'medium'
}

export const ListVariableSelect = ({
    variable,
    disabledReason,
    loadOnMount = true,
    onBlur,
    onChange,
    selectedValues = getListVariableSelectedValues(variable),
    size,
}: ListVariableSelectProps): JSX.Element => {
    const logic = variableValuesLogic({ variable, loadOnMount })
    const { loadVariableOptions } = useActions(logic)
    const { requestedValuesQueryKey, variableOptions, variableOptionsError, variableOptionsLoading } = useValues(logic)
    const isCurrentQuery = requestedValuesQueryKey === getValuesQueryKey(variable)
    const options =
        variable.values_query == null ? getStaticVariableOptions(variable) : isCurrentQuery ? variableOptions : []
    const currentError = isCurrentQuery ? variableOptionsError : null

    return (
        <LemonInputSelect
            className="w-full"
            mode={variable.is_multi ? 'multiple' : 'single'}
            value={selectedValues}
            options={options.map((option) => ({ key: option.value, label: option.label }))}
            onBlur={onBlur}
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
                !variable.is_multi && selectedValues.length > 0
                    ? {
                          children: 'Clear selection',
                          onClick: () => onChange(''),
                      }
                    : variable.values_query?.trim()
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

export const ListVariableFields = ({
    variable,
    updateVariable,
    defaultValuesQueryConnectionId,
}: DirectFieldProps<ListVariable> & { defaultValuesQueryConnectionId?: string | null }): JSX.Element => {
    const isQueryBacked = variable.values_query != null
    const logic = variableValuesLogic({
        variable,
        loadOnMount: isQueryBacked && Boolean(variable.values_query?.trim()),
    })
    const { loadVariableOptions } = useActions(logic)
    const { requestedValuesQueryKey, variableOptions, variableOptionsError, variableOptionsLoading } = useValues(logic)
    const { connectionOptions } = useValues(connectionSelectorLogic())
    const { maybeLoadConnectionOptions } = useActions(connectionSelectorLogic())
    useOnMountEffect(() => maybeLoadConnectionOptions())
    const isCurrentQuery = requestedValuesQueryKey === getValuesQueryKey(variable)
    const loadedOptions = isQueryBacked && isCurrentQuery ? variableOptions : []
    const availableOptions = isQueryBacked ? loadedOptions : getStaticVariableOptions(variable)
    const currentError = isCurrentQuery ? variableOptionsError : null
    const defaultValues = getListVariableSelectedValues({ ...variable, value: undefined })
    const showConnectionSelector = (connectionOptions?.length ?? 0) > 0 || Boolean(variable.values_query_connection_id)
    const hasCustomLabels = loadedOptions.some((option) => option.label !== option.value)

    return (
        <>
            <LemonField.Pure label="Options source" className="gap-1">
                <LemonSegmentedButton
                    className="w-full"
                    value={isQueryBacked ? 'query' : 'static'}
                    onChange={(source) =>
                        updateVariable({
                            ...variable,
                            values_query: source === 'query' ? '' : null,
                            values_query_connection_id:
                                source === 'query'
                                    ? (variable.values_query_connection_id ?? defaultValuesQueryConnectionId ?? null)
                                    : null,
                            default_value: variable.is_multi ? [] : '',
                        })
                    }
                    options={[
                        { value: 'static', label: 'Static options' },
                        { value: 'query', label: 'HogQL query' },
                    ]}
                />
            </LemonField.Pure>
            {isQueryBacked ? (
                <>
                    {showConnectionSelector && (
                        <LemonField.Pure label="Connection" className="gap-1">
                            <LemonSelect
                                value={variable.values_query_connection_id ?? POSTHOG_WAREHOUSE}
                                onChange={(value) =>
                                    updateVariable({
                                        ...variable,
                                        values_query_connection_id: value === POSTHOG_WAREHOUSE ? null : value,
                                    })
                                }
                                options={[
                                    { value: POSTHOG_WAREHOUSE, label: 'PostHog (ClickHouse)' },
                                    ...(connectionOptions ?? []).map((source) => ({
                                        value: source.id,
                                        label: getConnectionOptionLabel(source),
                                    })),
                                ]}
                                fullWidth
                            />
                        </LemonField.Pure>
                    )}
                    <LemonField.Pure
                        label="Options query"
                        className="gap-1"
                        info="The first column supplies the option values. An optional second column supplies their display labels. Queries without a LIMIT return up to 100 rows. Options load when the variable is shown, and results are cached for a few minutes."
                    >
                        <CodeEditorResizeable
                            language="hogQL"
                            value={variable.values_query ?? ''}
                            onChange={(value) => updateVariable({ ...variable, values_query: value ?? '' })}
                            minHeight="6rem"
                            maxHeight="40vh"
                        />
                        <div className="flex items-center justify-end gap-2">
                            {currentError ? (
                                <span className="text-danger text-xs">
                                    Couldn't load options. Check the query, then try again.
                                </span>
                            ) : loadedOptions.length > 0 ? (
                                <span className="text-success text-xs">
                                    Loaded {loadedOptions.length} option{loadedOptions.length === 1 ? '' : 's'}
                                </span>
                            ) : null}
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
                        {!currentError && loadedOptions.length > 0 ? (
                            <ul className="border rounded max-h-40 overflow-y-auto m-0 p-0 list-none">
                                {hasCustomLabels && (
                                    <li className="flex gap-2 px-2 py-1 text-xs font-medium text-secondary border-b sticky top-0 bg-bg-light">
                                        <span className="flex-1 min-w-0">Value</span>
                                        <span className="flex-1 min-w-0">Label</span>
                                    </li>
                                )}
                                {loadedOptions.map((option) => (
                                    <li
                                        key={option.value}
                                        className="flex gap-2 px-2 py-1 text-xs border-b last:border-b-0"
                                    >
                                        <span className="flex-1 min-w-0 truncate">{option.value}</span>
                                        {hasCustomLabels && (
                                            <span className="flex-1 min-w-0 text-secondary truncate">
                                                {option.label}
                                            </span>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        ) : null}
                    </LemonField.Pure>
                </>
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
                    options={availableOptions.map((option) => ({ key: option.value, label: option.label }))}
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

export const DateField = ({
    variable,
    updateVariable,
    onApply,
}: DirectFieldProps<DateVariable> & {
    /** Called when the calendar's own Apply button is pressed, so a caller can treat it as the commit. */
    onApply?: (value: string) => void
}): JSX.Element => {
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
                        step={1}
                        value={relativeValue.amount}
                        onChange={(amount) =>
                            updateVariable({
                                ...variable,
                                default_value: `-${normalizeRelativeDateAmount(amount)}${relativeValue.unit}`,
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
                    updateVariable={(date) => {
                        updateVariable({ ...variable, default_value: date })
                        onApply?.(date)
                    }}
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
