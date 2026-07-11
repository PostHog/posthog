import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'
import type { NotebookNodeSQLV2Result } from './NotebookNodeSQLV2'
import { notebookNodeSQLV2Logic } from './notebookNodeSQLV2Logic'

// Journey 11: an input widget bound to a kernel variable. Applying a new value runs a tiny
// python assignment cell in the sandbox kernel; the run's completion marks dependent cells
// stale (Journey 10) and re-runs them automatically.

export type NotebookNodeInputV2WidgetType = 'text' | 'number' | 'date' | 'select'

export type NotebookNodeInputV2Attributes = {
    // The kernel variable this widget sets, e.g. date_from.
    variable: string
    widgetType: NotebookNodeInputV2WidgetType
    // Newline- or comma-separated choices for the select widget.
    options: string
    value: string
    runId?: string | null
    result?: NotebookNodeSQLV2Result | null
}

const VARIABLE_PATTERN = /^[A-Za-z_]\w*$/

export const buildInputAssignmentCode = (
    variable: string,
    widgetType: NotebookNodeInputV2WidgetType,
    value: string
): string | null => {
    if (!VARIABLE_PATTERN.test(variable)) {
        return null
    }
    if (widgetType === 'number') {
        const numeric = Number(value)
        if (value.trim() === '' || !isFinite(numeric)) {
            return null
        }
        return `${variable} = ${numeric}`
    }
    // A JSON string literal is a valid python string literal (escapes are a shared subset).
    return `${variable} = ${JSON.stringify(value)}`
}

export const parseInputOptions = (options: string): string[] =>
    options
        .split(/[\n,]/)
        .map((option) => option.trim())
        .filter(Boolean)

const Component = ({ attributes, updateAttributes }: NotebookNodeProps<NotebookNodeInputV2Attributes>): JSX.Element => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { nodeId, notebookLogic } = useValues(nodeLogic)
    const notebookShortId = notebookLogic.props.shortId

    const dataLogic = notebookNodeSQLV2Logic({
        nodeId,
        notebookShortId,
        updateAttributes,
        runId: attributes.runId ?? null,
        hasResult: true, // an assignment has no result to recover on mount
        getContent: () => notebookLogic.values.content ?? null,
    })
    const { isRunning, runError, runBlockReason, isChainRunning } = useValues(dataLogic)
    const { runQuery } = useActions(dataLogic)

    // Text and number commit on blur/Enter, so the draft tracks keystrokes locally.
    const [draft, setDraft] = useState<string | null>(null)
    const value = draft ?? attributes.value ?? ''

    const apply = (nextValue: string): void => {
        setDraft(null)
        const code = buildInputAssignmentCode(attributes.variable ?? '', attributes.widgetType ?? 'text', nextValue)
        if (code === null || nextValue === attributes.value) {
            return
        }
        // Pin nodeId for the same reason runs do; persist the value for reloads.
        updateAttributes({ nodeId, variable: attributes.variable, value: nextValue })
        // The assignment reads nothing, so no refs; the run's completion marks dependents
        // stale and autoRunDependents re-runs them.
        runQuery(code, {}, { nodeType: 'python', autoRunDependents: true })
    }

    const disabledReason = isChainRunning
        ? 'Stale cells are being re-run'
        : isRunning
          ? 'Applying the previous change'
          : (runBlockReason ?? undefined)
    const widgetType = attributes.widgetType ?? 'text'

    return (
        <div
            data-attr="notebook-node-input-v2"
            className="flex items-center gap-2 p-2"
            onClick={(event) => event.stopPropagation()}
            onMouseDown={(event) => event.stopPropagation()}
        >
            <LemonLabel className="font-mono shrink-0">{attributes.variable || 'variable'}</LemonLabel>
            <div className="max-w-80 flex-1">
                {widgetType === 'select' ? (
                    <LemonSelect
                        size="small"
                        fullWidth
                        value={attributes.value || null}
                        options={parseInputOptions(attributes.options ?? '').map((option) => ({
                            value: option,
                            label: option,
                        }))}
                        onChange={(next) => (next === null ? undefined : apply(next))}
                        disabledReason={disabledReason}
                        placeholder="Pick a value"
                    />
                ) : widgetType === 'date' ? (
                    <LemonCalendarSelectInput
                        value={attributes.value ? dayjs(attributes.value) : null}
                        onChange={(date) => date && apply(date.format('YYYY-MM-DD'))}
                        format="YYYY-MM-DD"
                        placeholder="Pick a date"
                        buttonProps={{ size: 'small', disabledReason }}
                    />
                ) : (
                    <LemonInput
                        size="small"
                        fullWidth
                        value={value}
                        onChange={setDraft}
                        onBlur={() => draft !== null && apply(draft)}
                        onPressEnter={() => draft !== null && apply(draft)}
                        disabledReason={disabledReason}
                        placeholder={widgetType === 'number' ? '0' : 'Value'}
                    />
                )}
            </div>
            {isRunning ? <span className="text-xs text-muted shrink-0">Applying…</span> : null}
            {runError ? <span className="text-xs text-danger shrink-0">{runError}</span> : null}
            {attributes.variable && !VARIABLE_PATTERN.test(attributes.variable) ? (
                <span className="text-xs text-danger shrink-0">Not a valid python variable name</span>
            ) : null}
        </div>
    )
}

const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeInputV2Attributes>): JSX.Element => {
    return (
        <div className="flex flex-wrap items-center gap-2 p-2" onClick={(event) => event.stopPropagation()}>
            <LemonLabel>Variable</LemonLabel>
            <LemonInput
                size="small"
                className="font-mono"
                value={attributes.variable ?? ''}
                onChange={(variable) => updateAttributes({ variable })}
                placeholder="date_from"
            />
            <LemonLabel>Type</LemonLabel>
            <LemonSelect
                size="small"
                value={attributes.widgetType ?? 'text'}
                options={[
                    { value: 'text' as const, label: 'Text' },
                    { value: 'number' as const, label: 'Number' },
                    { value: 'date' as const, label: 'Date' },
                    { value: 'select' as const, label: 'Dropdown' },
                ]}
                onChange={(widgetType) => updateAttributes({ widgetType })}
            />
            {attributes.widgetType === 'select' ? (
                <>
                    <LemonLabel>Choices</LemonLabel>
                    <LemonInput
                        size="small"
                        value={attributes.options ?? ''}
                        onChange={(options) => updateAttributes({ options })}
                        placeholder="Comma-separated choices"
                    />
                </>
            ) : null}
        </div>
    )
}

export const NotebookNodeInputV2 = createPostHogWidgetNode<NotebookNodeInputV2Attributes>({
    nodeType: NotebookNodeType.InputV2,
    titlePlaceholder: 'Input',
    Component,
    heightEstimate: 48,
    minHeight: 40,
    resizeable: false,
    startExpanded: true,
    attributes: {
        variable: {
            default: 'input_value',
        },
        widgetType: {
            default: 'text',
        },
        options: {
            default: '',
        },
        value: {
            default: '',
        },
        runId: {
            default: null,
        },
        result: {
            default: null,
        },
    },
    Settings,
    settingsPlacement: 'inline',
    serializedText: (attrs) => `${attrs.variable} = ${attrs.value}`,
})
