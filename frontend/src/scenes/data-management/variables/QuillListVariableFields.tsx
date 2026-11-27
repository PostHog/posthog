import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Field, FieldLabel, Switch, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { QuillSortableChipInput } from 'lib/components/QuillSortableChipInput/QuillSortableChipInput'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { getListVariableValues } from '~/queries/nodes/DataVisualization/Components/Variables/VariableFields'
import { getListVariableSelectedValues } from '~/queries/nodes/DataVisualization/Components/Variables/variableUtils'
import {
    getStaticVariableOptions,
    getValuesQueryKey,
    variableValuesLogic,
} from '~/queries/nodes/DataVisualization/Components/Variables/variableValuesLogic'
import { ListVariable } from '~/queries/nodes/DataVisualization/types'

import { connectionSelectorLogic } from 'products/data_warehouse/frontend/shared/logics/connectionSelectorLogic'

import { QuillListVariableQueryFields } from './QuillListVariableQueryFields'
import { QuillVariableOptionsCombobox } from './QuillVariableOptionsCombobox'

export interface QuillListVariableFieldsProps {
    variable: ListVariable
    updateVariable: (variable: ListVariable) => void
}

/** Quill sibling of `ListVariableFields`, for the SQL variable edit page. Writes the same variable shape. */
export function QuillListVariableFields({ variable, updateVariable }: QuillListVariableFieldsProps): JSX.Element {
    const id = useId()
    const isQueryBacked = variable.values_query != null
    const logic = variableValuesLogic({
        variable,
        loadOnMount: isQueryBacked && Boolean(variable.values_query?.trim()),
    })
    const { requestedValuesQueryKey, variableOptions, variableOptionsLoading } = useValues(logic)
    const { maybeLoadConnectionOptions } = useActions(connectionSelectorLogic())
    useOnMountEffect(() => maybeLoadConnectionOptions())
    const isCurrentQuery = requestedValuesQueryKey === getValuesQueryKey(variable)
    const loadedOptions = isQueryBacked && isCurrentQuery ? variableOptions : []
    const availableOptions = isQueryBacked ? loadedOptions : getStaticVariableOptions(variable)
    const defaultValues = getListVariableSelectedValues({ ...variable, value: undefined })
    return (
        <>
            <Field>
                <FieldLabel htmlFor={`${id}-source`}>Options source</FieldLabel>
                <ToggleGroup
                    id={`${id}-source`}
                    variant="outline"
                    aria-label="Options source"
                    className="w-full"
                    value={[isQueryBacked ? 'query' : 'static']}
                    onValueChange={(next: string[]) => {
                        const source = next[0]
                        if (!source || source === (isQueryBacked ? 'query' : 'static')) {
                            return
                        }
                        updateVariable({
                            ...variable,
                            values_query: source === 'query' ? '' : null,
                            values_query_connection_id:
                                source === 'query' ? (variable.values_query_connection_id ?? null) : null,
                            default_value: variable.is_multi ? [] : '',
                        })
                    }}
                >
                    <ToggleGroupItem value="static" className="flex-1">
                        Static options
                    </ToggleGroupItem>
                    <ToggleGroupItem value="query" className="flex-1">
                        HogQL query
                    </ToggleGroupItem>
                </ToggleGroup>
            </Field>
            {isQueryBacked ? (
                <QuillListVariableQueryFields variable={variable} updateVariable={updateVariable} />
            ) : (
                <Field>
                    <FieldLabel htmlFor={`${id}-options`}>Options</FieldLabel>
                    <QuillSortableChipInput
                        id={`${id}-options`}
                        value={getListVariableValues(variable)}
                        onChange={(values) => updateVariable({ ...variable, values })}
                        placeholder="Options..."
                    />
                </Field>
            )}
            <Field orientation="horizontal" className="w-fit">
                <Switch
                    id={`${id}-multi`}
                    checked={Boolean(variable.is_multi)}
                    onCheckedChange={(isMulti: boolean) => {
                        const normalizedDefault = isMulti ? defaultValues : (defaultValues[0] ?? '')
                        updateVariable({ ...variable, is_multi: isMulti, default_value: normalizedDefault })
                    }}
                />
                <FieldLabel htmlFor={`${id}-multi`}>Allow multiple selections</FieldLabel>
            </Field>
            <Field>
                <FieldLabel htmlFor={`${id}-default`}>Default value</FieldLabel>
                <QuillVariableOptionsCombobox
                    id={`${id}-default`}
                    multiple={Boolean(variable.is_multi)}
                    options={availableOptions}
                    selectedValues={defaultValues}
                    onChange={(values) =>
                        updateVariable({
                            ...variable,
                            default_value: variable.is_multi ? values : (values[0] ?? ''),
                        })
                    }
                    placeholder={variableOptionsLoading ? 'Loading options...' : 'Select a default value'}
                    emptyState={isQueryBacked ? 'Preview the query to load options.' : undefined}
                />
            </Field>
        </>
    )
}
