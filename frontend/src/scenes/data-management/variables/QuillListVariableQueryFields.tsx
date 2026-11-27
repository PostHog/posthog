import { useActions, useValues } from 'kea'

import { Button, Field, FieldDescription, FieldLabel, Text } from '@posthog/quill'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import {
    getValuesQueryKey,
    variableValuesLogic,
} from '~/queries/nodes/DataVisualization/Components/Variables/variableValuesLogic'
import { ListVariable } from '~/queries/nodes/DataVisualization/types'

import { QuillVariableConnectionSelect } from './QuillVariableConnectionSelect'
import { QuillVariableOptionsPreview } from './QuillVariableOptionsPreview'

export interface QuillListVariableQueryFieldsProps {
    variable: ListVariable
    updateVariable: (variable: ListVariable) => void
}

/** The connection, query and option preview of a query-backed list variable, on the SQL variable edit page. */
export function QuillListVariableQueryFields({
    variable,
    updateVariable,
}: QuillListVariableQueryFieldsProps): JSX.Element {
    const logic = variableValuesLogic({ variable, loadOnMount: Boolean(variable.values_query?.trim()) })
    const { loadVariableOptions } = useActions(logic)
    const { requestedValuesQueryKey, variableOptions, variableOptionsError, variableOptionsLoading } = useValues(logic)
    const isCurrentQuery = requestedValuesQueryKey === getValuesQueryKey(variable)
    const loadedOptions = isCurrentQuery ? variableOptions : []
    const currentError = isCurrentQuery ? variableOptionsError : null

    return (
        <>
            <QuillVariableConnectionSelect variable={variable} updateVariable={updateVariable} />
            <Field>
                <FieldLabel>Options query</FieldLabel>
                <FieldDescription>
                    The first column supplies the option values. An optional second column supplies their display
                    labels. Queries without a LIMIT return up to 100 rows. Options load when the variable is shown, and
                    results are cached for a few minutes.
                </FieldDescription>
                <CodeEditorResizeable
                    language="hogQL"
                    value={variable.values_query ?? ''}
                    onChange={(value) => updateVariable({ ...variable, values_query: value ?? '' })}
                    minHeight="6rem"
                    maxHeight="40vh"
                />
                <div className="flex flex-wrap items-center justify-end gap-2">
                    {currentError ? (
                        <Text size="xs" render={<span />} className="text-destructive-foreground">
                            Couldn't load options. Check the query, then try again.
                        </Text>
                    ) : loadedOptions.length > 0 ? (
                        <Text size="xs" render={<span />} className="text-success-foreground">
                            <span>Loaded&nbsp;</span>
                            <span translate="no">{loadedOptions.length}</span>
                            <span>&nbsp;option{loadedOptions.length === 1 ? '' : 's'}</span>
                        </Text>
                    ) : null}
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => loadVariableOptions(variable)}
                        loading={variableOptionsLoading}
                        disabledReason={!variable.values_query?.trim() ? 'Enter a query first' : undefined}
                    >
                        Preview options
                    </Button>
                </div>
                {!currentError && loadedOptions.length > 0 ? (
                    <QuillVariableOptionsPreview options={loadedOptions} />
                ) : null}
            </Field>
        </>
    )
}
