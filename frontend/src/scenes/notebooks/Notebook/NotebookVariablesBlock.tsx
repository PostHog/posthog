import { useActions, useMountedLogic, useValues } from 'kea'
import { useId } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import { NotebookComponentBlockNode, NotebookComponentRenderProps } from 'lib/components/MarkdownNotebook/types'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import { notebookLogic } from './notebookLogic'
import { notebookNodeStalenessLogic } from './notebookNodeStalenessLogic'
import {
    NOTEBOOK_VARIABLE_TYPES,
    NotebookVariable,
    NotebookVariableType,
    NotebookVariableValue,
    coerceNotebookVariableValue,
    getNotebookVariableConflictNames,
    getNotebookVariableErrors,
    parseNotebookVariableItems,
    serializeNotebookVariableItems,
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

export function getNotebookVariablesTitle(node: NotebookComponentBlockNode): string | null {
    const names = parseNotebookVariableItems(node.props)
        .map((variable) => variable.name)
        .filter(Boolean)
    return names.length ? names.join(', ') : null
}

/** Shared state and the write path for both panels: the notebook's variables and how to save them. */
function useNotebookVariables({ node, updateProps }: Pick<NotebookComponentRenderProps, 'node' | 'updateProps'>): {
    variables: NotebookVariable[]
    errors: (string | null)[]
    save: (next: NotebookVariable[]) => void
} {
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const { content } = useValues(mountedNotebookLogic)
    const { variablesChanged } = useActions(notebookNodeStalenessLogic({ shortId: mountedNotebookLogic.props.shortId }))

    const variables = parseNotebookVariableItems(node.props)
    const errors = getNotebookVariableErrors(variables, getNotebookVariableConflictNames(content))

    const save = (next: NotebookVariable[]): void => {
        updateProps({ items: serializeNotebookVariableItems(next) })
        // A cell that read one of these computed its result from the old value, so it no longer
        // reflects the notebook as it stands — the same contract as an upstream cell's run landing.
        // Compared by name rather than by position: removing a variable shifts every later index.
        const previousByName = new Map(variables.map((variable) => [variable.name, variable.value]))
        const nextByName = new Map(next.map((variable) => [variable.name, variable.value]))
        const affected = new Set<string>()
        for (const [name, value] of nextByName) {
            if (!previousByName.has(name) || previousByName.get(name) !== value) {
                affected.add(name)
            }
        }
        // A rename reaches here as both halves: the old name disappeared and the new one appeared.
        for (const name of previousByName.keys()) {
            if (!nextByName.has(name)) {
                affected.add(name)
            }
        }
        variablesChanged([...affected].filter(Boolean), content)
    }

    return { variables, errors, save }
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
            value={typeof variable.value === 'string' ? variable.value : ''}
            onChange={(value) => onChange(value)}
        />
    )
}

/**
 * The read panel: every declared variable with its value, editable in place. Values are the
 * point of the block — a reader adjusts them and re-runs — so they stay editable here while
 * names and types are only settable from the filters panel below.
 */
export function NotebookVariablesBlock(props: NotebookComponentRenderProps): JSX.Element {
    const { variables, errors, save } = useNotebookVariables(props)
    return (
        <NotebookVariablesValuePanel
            variables={variables}
            errors={errors}
            disabled={(props.notebookMode ?? props.mode) === 'view'}
            onChange={save}
        />
    )
}

/** Presentational half of the read panel, so the rendering can be tested without the notebook. */
export function NotebookVariablesValuePanel({
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
    const save = onChange
    const isReadOnly = disabled
    // Scoped to this block: a notebook can hold more than one, and duplicate DOM ids would
    // point the second block's labels at the first block's inputs.
    const idPrefix = useId()

    if (!variables.length) {
        return (
            <div className="MarkdownNotebook__component-preview text-sm text-secondary">
                No variables yet. Add one in the filters panel, then read it as <code>{'{name}'}</code> in a SQL cell or
                as a plain variable in a Python cell.
            </div>
        )
    }

    return (
        <div className="MarkdownNotebook__component-form">
            {variables.map((variable, index) => (
                <div key={index} className="flex flex-col gap-1">
                    <div className="grid grid-cols-[minmax(6rem,12rem)_1fr] items-center gap-2">
                        {/* A real label, so the name reads out with its control and clicking it focuses the value. */}
                        <label
                            htmlFor={`${idPrefix}-${index}`}
                            className="font-mono text-sm truncate"
                            title={variable.name}
                        >
                            {variable.name || <span className="text-secondary italic">Unnamed</span>}
                        </label>
                        <NotebookVariableValueInput
                            variable={variable}
                            controlId={`${idPrefix}-${index}`}
                            disabled={isReadOnly}
                            onChange={(value) =>
                                save(variables.map((other, i) => (i === index ? { ...other, value } : other)))
                            }
                        />
                    </div>
                    {errors[index] ? <span className="text-xs text-danger">{errors[index]}</span> : null}
                </div>
            ))}
        </div>
    )
}

/** The filters panel: declare the variables themselves — name, type, and whether they exist. */
export function NotebookVariablesEditor(props: NotebookComponentRenderProps): JSX.Element {
    const { variables, errors, save } = useNotebookVariables(props)
    return (
        <NotebookVariablesDeclarationPanel
            variables={variables}
            errors={errors}
            onChange={save}
            autoFocusLast={wasNotebookNodeJustInserted(props.node.id)}
        />
    )
}

/** Presentational half of the filters panel; see NotebookVariablesValuePanel. */
export function NotebookVariablesDeclarationPanel({
    variables,
    errors,
    onChange,
    autoFocusLast = false,
}: {
    variables: NotebookVariable[]
    errors: (string | null)[]
    onChange: (next: NotebookVariable[]) => void
    autoFocusLast?: boolean
}): JSX.Element {
    const save = onChange

    const addVariable = (): void => {
        save([...variables, { name: '', type: 'string', value: DEFAULT_VALUE_BY_TYPE.string }])
    }

    return (
        <div className="MarkdownNotebook__component-form">
            {variables.map((variable, index) => (
                <div key={index} className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <LemonInput
                            size="small"
                            className="flex-1 font-mono"
                            placeholder="variable_name"
                            value={variable.name}
                            onChange={(name) =>
                                save(variables.map((other, i) => (i === index ? { ...other, name } : other)))
                            }
                            autoFocus={autoFocusLast && index === variables.length - 1}
                            aria-label="Variable name"
                        />
                        <LemonSelect
                            size="small"
                            value={variable.type}
                            onChange={(type) =>
                                save(
                                    variables.map((other, i) =>
                                        i === index
                                            ? {
                                                  ...other,
                                                  type,
                                                  // A value left over from the previous type would
                                                  // serialize as the wrong shape, so refit it.
                                                  value:
                                                      coerceNotebookVariableValue(type, other.value) ??
                                                      DEFAULT_VALUE_BY_TYPE[type],
                                              }
                                            : other
                                    )
                                )
                            }
                            options={NOTEBOOK_VARIABLE_TYPES.map((type) => ({ value: type, label: TYPE_LABELS[type] }))}
                            aria-label="Variable type"
                        />
                        <LemonButton
                            size="small"
                            icon={<IconTrash />}
                            tooltip="Remove variable"
                            onClick={() => save(variables.filter((_, i) => i !== index))}
                            aria-label={`Remove ${variable.name || 'variable'}`}
                        />
                    </div>
                    {errors[index] ? <span className="text-xs text-danger">{errors[index]}</span> : null}
                </div>
            ))}
            <div>
                <LemonButton size="small" type="secondary" icon={<IconPlus />} onClick={addVariable}>
                    Add variable
                </LemonButton>
            </div>
        </div>
    )
}
