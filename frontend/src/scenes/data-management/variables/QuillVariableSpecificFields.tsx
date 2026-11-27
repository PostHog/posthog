import { useId } from 'react'

import { Field, FieldLabel, Input, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { DateVariable, ListVariable, Variable } from '~/queries/nodes/DataVisualization/types'

import { QuillDateVariableField } from './QuillDateVariableField'
import { QuillListVariableFields } from './QuillListVariableFields'
import { QuillNumberVariableInput } from './QuillNumberVariableInput'

export interface QuillVariableSpecificFieldsProps {
    variable: Variable
    updateVariable: (variable: Variable) => void
}

/**
 * Quill sibling of `VariableSpecificFields`, for the SQL variable edit page.
 * The SQL editor's variable modal keeps the Lemon version.
 */
export function QuillVariableSpecificFields({
    variable,
    updateVariable,
}: QuillVariableSpecificFieldsProps): JSX.Element {
    const id = useId()

    if (variable.type === 'List') {
        return (
            <QuillListVariableFields
                variable={variable}
                updateVariable={updateVariable as (variable: ListVariable) => void}
            />
        )
    }

    return (
        <Field>
            <FieldLabel htmlFor={id}>Default value</FieldLabel>
            {variable.type === 'String' ? (
                <Input
                    id={id}
                    placeholder="Default value"
                    value={variable.default_value}
                    onChange={(event) => updateVariable({ ...variable, default_value: event.target.value })}
                />
            ) : variable.type === 'Number' ? (
                <QuillNumberVariableInput id={id} variable={variable} updateVariable={updateVariable} />
            ) : variable.type === 'Boolean' ? (
                <ToggleGroup
                    id={id}
                    variant="outline"
                    aria-label="Default value"
                    className="w-full"
                    value={[variable.default_value ? 'true' : 'false']}
                    onValueChange={(next: string[]) => {
                        if (next[0]) {
                            updateVariable({ ...variable, default_value: next[0] === 'true' })
                        }
                    }}
                >
                    <ToggleGroupItem value="true" className="flex-1">
                        true
                    </ToggleGroupItem>
                    <ToggleGroupItem value="false" className="flex-1">
                        false
                    </ToggleGroupItem>
                </ToggleGroup>
            ) : (
                <QuillDateVariableField
                    id={id}
                    variable={variable as DateVariable}
                    updateVariable={updateVariable as (variable: DateVariable) => void}
                />
            )}
        </Field>
    )
}
