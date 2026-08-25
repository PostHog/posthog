import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import { notebookLogic } from './notebookLogic'
import {
    MAX_NOTEBOOK_VARIABLES,
    MAX_NOTEBOOK_VARIABLE_VALUE_CHARS,
    NOTEBOOK_VARIABLE_TYPES,
    NotebookVariable,
    NotebookVariableType,
    NotebookVariableValue,
    coerceNotebookVariableValue,
} from './notebookVariables'

const TYPE_LABELS: Record<NotebookVariableType, string> = {
    string: 'String',
    number: 'Number',
    boolean: 'Boolean',
    date: 'Date',
}

const DEFAULT_VALUE_BY_TYPE: Record<NotebookVariableType, NotebookVariableValue> = {
    string: '',
    number: 0,
    boolean: false,
    date: '',
}

function NotebookVariableValueInput({
    variable,
    controlId,
    disabled,
    onChange,
}: {
    variable: NotebookVariable
    controlId: string
    disabled: boolean
    onChange: (value: NotebookVariableValue) => void
}): JSX.Element {
    if (variable.type === 'boolean') {
        return (
            <LemonCheckbox id={controlId} checked={variable.value === true} disabled={disabled} onChange={onChange} />
        )
    }

    if (variable.type === 'number') {
        return (
            <LemonInput
                id={controlId}
                type="number"
                size="small"
                fullWidth
                disabled={disabled}
                value={typeof variable.value === 'number' ? variable.value : undefined}
                onChange={(value) => onChange(value ?? null)}
            />
        )
    }

    if (variable.type === 'date') {
        const value = typeof variable.value === 'string' && variable.value ? dayjs(variable.value) : null
        return (
            <LemonCalendarSelectInput
                value={value?.isValid() ? value : null}
                onChange={(date) => onChange(date ? date.format('YYYY-MM-DD') : '')}
                buttonProps={{
                    id: controlId,
                    size: 'small',
                    disabledReason: disabled ? 'This notebook is read-only' : undefined,
                }}
                placeholder="Select a date"
            />
        )
    }

    return (
        <LemonInput
            id={controlId}
            size="small"
            fullWidth
            disabled={disabled}
            maxLength={MAX_NOTEBOOK_VARIABLE_VALUE_CHARS}
            value={typeof variable.value === 'string' ? variable.value : ''}
            onChange={(value) => onChange(value)}
        />
    )
}

/**
 * The notebook's variables, one row each: name, type, value, delete. A property of the notebook
 * rather than a block in the document, so it hangs under the header and cannot be reordered,
 * duplicated, or deleted as content.
 */
export function NotebookVariablesPanel({
    variables,
    errors,
    disabled,
    onChange,
}: {
    variables: NotebookVariable[]
    errors: (string | null)[]
    disabled: boolean
    onChange: (next: NotebookVariable[]) => void
}): JSX.Element {
    // Scoped to this panel: two panels on one page would otherwise point their labels at each
    // other's inputs.
    const idPrefix = useId()

    const update = (index: number, patch: Partial<NotebookVariable>): void =>
        onChange(variables.map((variable, i) => (i === index ? { ...variable, ...patch } : variable)))

    return (
        <div className="NotebookVariables mx-auto flex w-[70%] min-w-0 flex-col gap-2 rounded border border-primary bg-surface-secondary p-2">
            {variables.length === 0 ? (
                <p className="m-0 text-xs text-secondary">
                    No variables yet. Add one, then read it as <code>{'{name}'}</code> in a SQL cell or as a plain
                    variable in a Python cell.
                </p>
            ) : (
                variables.map((variable, index) => (
                    <div key={index} className="flex flex-col gap-1">
                        {/* A grid, not a flex row: the type select sizes to its label, so on a flex
                            row every value input would start at a different x. Fixed tracks line
                            the values up down the column. */}
                        <div className="grid grid-cols-[minmax(6rem,10rem)_7rem_minmax(0,1fr)_auto] items-center gap-x-2">
                            <LemonInput
                                size="small"
                                className="font-mono"
                                placeholder="variable_name"
                                value={variable.name}
                                disabled={disabled}
                                onChange={(name) => update(index, { name })}
                                aria-label={`Name of variable ${index + 1}`}
                            />
                            <LemonSelect
                                size="small"
                                fullWidth
                                value={variable.type}
                                disabled={disabled}
                                onChange={(type) =>
                                    update(index, {
                                        type,
                                        // A value left over from the previous type would serialize
                                        // as the wrong shape, so refit it.
                                        value:
                                            coerceNotebookVariableValue(type, variable.value) ??
                                            DEFAULT_VALUE_BY_TYPE[type],
                                    })
                                }
                                options={NOTEBOOK_VARIABLE_TYPES.map((type) => ({
                                    value: type,
                                    label: TYPE_LABELS[type],
                                }))}
                                aria-label={`Type of ${variable.name || `variable ${index + 1}`}`}
                            />
                            {/* Wider gap here than between name and type: it separates what the
                                variable is from what it currently holds. */}
                            <div className="ml-4">
                                {/* The name sits in an editable field, so it cannot label the
                                    value. A hidden label gives the control its own name. */}
                                <label htmlFor={`${idPrefix}-${index}`} className="sr-only">
                                    {`Value of ${variable.name || `variable ${index + 1}`}`}
                                </label>
                                <NotebookVariableValueInput
                                    variable={variable}
                                    controlId={`${idPrefix}-${index}`}
                                    disabled={disabled}
                                    onChange={(value) => update(index, { value })}
                                />
                            </div>
                            <LemonButton
                                size="small"
                                icon={<IconTrash />}
                                tooltip="Remove variable"
                                disabledReason={disabled ? 'This notebook is read-only' : undefined}
                                onClick={() => onChange(variables.filter((_, i) => i !== index))}
                                aria-label={`Remove ${variable.name || `variable ${index + 1}`}`}
                            />
                        </div>
                        {errors[index] ? <span className="text-xs text-danger">{errors[index]}</span> : null}
                    </div>
                ))
            )}
            <div>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPlus />}
                    disabledReason={
                        disabled
                            ? 'This notebook is read-only'
                            : variables.length >= MAX_NOTEBOOK_VARIABLES
                              ? `A notebook can have up to ${MAX_NOTEBOOK_VARIABLES} variables`
                              : undefined
                    }
                    onClick={() => onChange([...variables, { name: '', type: 'string', value: '' }])}
                >
                    Add variable
                </LemonButton>
            </div>
        </div>
    )
}

/** The panel bound to the notebook it belongs to. Renders nothing unless the bar is open. */
export function NotebookVariablesBar(): JSX.Element | null {
    const { variables, variableErrors, showVariables, isEditable } = useValues(notebookLogic)
    const { setVariables } = useActions(notebookLogic)

    if (!showVariables) {
        return null
    }

    return (
        <div className="mb-2">
            <NotebookVariablesPanel
                variables={variables}
                errors={variableErrors}
                disabled={!isEditable}
                onChange={setVariables}
            />
        </div>
    )
}
