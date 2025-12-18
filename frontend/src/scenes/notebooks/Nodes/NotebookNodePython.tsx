import { useActions, useValues } from 'kea'
import { ComponentProps, useCallback, useEffect, useMemo, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconPlayFilled, IconRefresh, IconStopFilled } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Popover } from '@posthog/lemon-ui'

import api from 'lib/api'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { TZLabel } from 'lib/components/TZLabel'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'

import { notebookLogic } from '../Notebook/notebookLogic'
import {
    NotebookKernelExecutionResponse,
    NotebookKernelStatus,
    NotebookKernelVariable,
    NotebookNodeAttributeProperties,
    NotebookNodeProps,
    NotebookNodeType,
} from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const DEFAULT_CODE = '# Write Python code to run inside your notebook kernel\nresult = 1 + 1\nresult'

const stringifyOutput = (output: unknown): string => {
    try {
        return typeof output === 'string' ? output : JSON.stringify(output, null, 2)
    } catch {
        return String(output)
    }
}

const formatOutputText = (output: unknown): string | null => {
    if (output === null || output === undefined) {
        return null
    }

    if (Array.isArray(output)) {
        return output.map(stringifyOutput).join('\n')
    }

    return stringifyOutput(output)
}

type NotebookNodePythonAttributes = {
    code: string
    stdout?: string | null
    stderr?: string | null
    result?: Record<string, any> | null
    variables?: NotebookKernelVariable[]
    status?: NotebookKernelExecutionResponse['status']
    executionCount?: number | null
    lastRunAt?: string | null
    errorName?: string | null
    traceback?: string[]
    kernel?: NotebookKernelStatus | null
}

const statusToTag = (
    status?: NotebookKernelExecutionResponse['status']
): 'default' | 'success' | 'warning' | 'danger' => {
    if (status === 'ok') {
        return 'success'
    }
    if (status === 'timeout') {
        return 'warning'
    }
    if (status === 'error') {
        return 'danger'
    }
    return 'default'
}

const HIDDEN_VARIABLE_NAMES = new Set(['In', 'Out'])

const usePythonExecution = (
    code: string,
    attributes: NotebookNodePythonAttributes,
    updateAttributes: NotebookNodeProps<NotebookNodePythonAttributes>['updateAttributes']
): {
    runCode: (codeOverride?: string) => Promise<void>
    restartKernel: () => Promise<void>
    stopKernel: () => Promise<void>
    running: boolean
    localError: string | null
    setLocalError: (error: string | null) => void
} => {
    const { shortId } = useValues(notebookLogic)
    const [running, setRunning] = useState(false)
    const [localError, setLocalError] = useState<string | null>(null)

    const handleExecution = useCallback(
        (response: NotebookKernelExecutionResponse, executedCode: string) => {
            updateAttributes({
                code: executedCode,
                stdout: response.stdout,
                stderr: response.stderr,
                result: response.result || null,
                variables: response.variables || [],
                status: response.status,
                executionCount: response.execution_count ?? null,
                lastRunAt: response.completed_at,
                errorName: response.error_name || null,
                traceback: response.traceback || [],
                kernel: response.kernel,
            })
        },
        [updateAttributes]
    )

    const runCode = useCallback(
        async (codeOverride?: string) => {
            setRunning(true)
            setLocalError(null)
            const codeToRun = codeOverride ?? code ?? DEFAULT_CODE
            try {
                const response = await api.notebooks.executeKernel(shortId, {
                    code: codeToRun,
                    return_variables: true,
                })
                handleExecution(response, codeToRun)
            } catch (error: any) {
                setLocalError(error?.message ?? 'Unable to run code')
            } finally {
                setRunning(false)
            }
        },
        [code, handleExecution, shortId]
    )

    const restartKernel = useCallback(async () => {
        setLocalError(null)
        try {
            const status = await api.notebooks.restartKernel(shortId)
            updateAttributes({ kernel: status })
        } catch (error: any) {
            setLocalError(error?.message ?? 'Unable to restart kernel')
        }
    }, [shortId, updateAttributes])

    const stopKernel = useCallback(async () => {
        setLocalError(null)
        try {
            await api.notebooks.stopKernel(shortId)
            updateAttributes({ kernel: null })
        } catch (error: any) {
            setLocalError(error?.message ?? 'Unable to stop kernel')
        }
    }, [shortId, updateAttributes])

    return { runCode, restartKernel, stopKernel, running, localError, setLocalError }
}

const NotebookNodePythonComponent = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodePythonAttributes>): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)
    const { editingNodeId } = useValues(notebookLogic)
    const { setTitlePlaceholder, setExpanded, toggleEditing } = useActions(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder('Python')
    }, [setTitlePlaceholder])

    const variables = attributes.variables || []
    const filteredVariables = useMemo(
        () => variables.filter((variable) => !HIDDEN_VARIABLE_NAMES.has(variable.name)),
        [variables]
    )
    const hasVariables = filteredVariables.length > 0
    const hasRun = attributes.executionCount !== null && attributes.executionCount !== undefined
    const isEditingThisNode = editingNodeId === attributes.nodeId

    const { runCode, running, localError, setLocalError } = usePythonExecution(
        attributes.code || DEFAULT_CODE,
        attributes,
        updateAttributes
    )

    const resultText = useMemo(
        () => (attributes.result ? formatOutputText(attributes.result['text/plain'] ?? attributes.result) : null),
        [attributes.result]
    )
    const stdoutText = useMemo(() => formatOutputText(attributes.stdout), [attributes.stdout])
    const stderrText = useMemo(() => formatOutputText(attributes.stderr), [attributes.stderr])
    const tracebackText = useMemo(() => formatOutputText(attributes.traceback?.join('\n')), [attributes.traceback])
    const hasOutputs = Boolean(resultText || stdoutText || stderrText || tracebackText || hasVariables || hasRun)

    if (!expanded) {
        return null
    }

    const toggleEditorVisibility = (): void => {
        if (isEditingThisNode) {
            toggleEditing(false)
        } else {
            setExpanded(true)
            toggleEditing(true)
        }
    }

    return (
        <div className="space-y-2">
            {!isEditingThisNode ? (
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-1">
                        <LemonButton
                            type="primary"
                            size="xsmall"
                            icon={<IconPlayFilled />}
                            loading={running}
                            onClick={() => runCode()}
                        >
                            Run
                        </LemonButton>
                        <LemonButton size="xsmall" type="secondary" onClick={toggleEditorVisibility}>
                            Expand code
                        </LemonButton>
                    </div>
                    <PythonRunMeta attributes={attributes} />
                </div>
            ) : null}

            {localError ? (
                <LemonBanner type="error" onClose={() => setLocalError(null)}>
                    {localError}
                </LemonBanner>
            ) : null}

            {hasOutputs ? (
                <div className="space-y-2 overflow-auto max-h-[20rem] pr-1">
                    {resultText ? (
                        <OutputBlock title="Result">
                            <CodeSnippet language={Language.Python} wrap compact>
                                {resultText}
                            </CodeSnippet>
                        </OutputBlock>
                    ) : null}
                    {stdoutText ? (
                        <OutputBlock title="Stdout">
                            <CodeSnippet language={Language.Text} wrap compact ansi>
                                {stdoutText}
                            </CodeSnippet>
                        </OutputBlock>
                    ) : null}
                    {stderrText ? (
                        <OutputBlock title="Stderr">
                            <CodeSnippet language={Language.Text} wrap compact ansi>
                                {stderrText}
                            </CodeSnippet>
                        </OutputBlock>
                    ) : null}
                    {tracebackText ? (
                        <OutputBlock title={attributes.errorName ? `Error: ${attributes.errorName}` : 'Error'}>
                            <CodeSnippet language={Language.Text} wrap compact>
                                {tracebackText}
                            </CodeSnippet>
                        </OutputBlock>
                    ) : null}
                    {hasVariables || hasRun ? (
                        <OutputBlock title="Variables">
                            <VariablesOutput variables={filteredVariables} hasRun={hasRun} />
                        </OutputBlock>
                    ) : null}
                </div>
            ) : (
                <LemonBanner type="info">
                    Use Expand code to edit and run your Python code. Results will appear here once the code runs.
                </LemonBanner>
            )}
        </div>
    )
}

const OutputBlock = ({ title, children }: { title: string; children: JSX.Element }): JSX.Element => (
    <div className="space-y-1">
        <div className="text-xs text-muted-alt">{title}</div>
        {children}
    </div>
)

const VARIABLE_KIND_META: Record<
    NotebookKernelVariable['kind'],
    { label: string; tag: ComponentProps<typeof LemonTag>['type'] }
> = {
    hogql_ast: { label: 'HogQL AST', tag: 'primary' },
    json: { label: 'JSON', tag: 'success' },
    scalar: { label: 'Value', tag: 'muted' },
}

const VariablesOutput = ({
    variables,
    hasRun,
}: {
    variables: NotebookKernelVariable[]
    hasRun: boolean
}): JSX.Element => {
    const [openVariable, setOpenVariable] = useState<string | null>(null)

    if (!variables.length) {
        return (
            <div className="text-xs text-muted-alt">
                {hasRun ? 'No variables captured yet.' : 'Run code to populate variables.'}
            </div>
        )
    }

    return (
        <div className="flex items-center gap-2 overflow-x-auto pb-1">
            {variables.map((variable) => {
                const kindMeta = VARIABLE_KIND_META[variable.kind] || VARIABLE_KIND_META.scalar
                const isOpen = openVariable === variable.name

                return (
                    <Popover
                        key={variable.name}
                        visible={isOpen}
                        onClickOutside={() => setOpenVariable(null)}
                        overlay={
                            <div className="space-y-2 max-w-[28rem]">
                                <div className="flex flex-wrap items-center gap-2">
                                    <code className="text-xs font-semibold leading-tight">{variable.name}</code>
                                    <LemonTag type={kindMeta.tag} size="small">
                                        {kindMeta.label}
                                    </LemonTag>
                                    <span className="text-xs text-muted-alt">{variable.type}</span>
                                </div>
                                <CodeSnippet language={Language.Text} wrap compact>
                                    {variable.repr}
                                </CodeSnippet>
                            </div>
                        }
                        placement="bottom-start"
                    >
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            className="shrink-0"
                            onClick={(event) => {
                                event.stopPropagation()
                                setOpenVariable(isOpen ? null : variable.name)
                            }}
                        >
                            <span className="flex items-center gap-1">
                                <code className="text-xs font-semibold leading-tight">{variable.name}</code>
                                <LemonTag type={kindMeta.tag} size="small">
                                    {kindMeta.label}
                                </LemonTag>
                            </span>
                        </LemonButton>
                    </Popover>
                )
            })}
        </div>
    )
}

const PythonRunMeta = ({ attributes }: { attributes: NotebookNodePythonAttributes }): JSX.Element => (
    <div className="flex flex-wrap items-center gap-1">
        <LemonTag type={attributes.kernel?.alive ? 'success' : 'default'}>
            {attributes.kernel?.alive ? 'Kernel running' : 'Kernel stopped'}
        </LemonTag>
        {attributes.executionCount ? <LemonTag>Run #{attributes.executionCount}</LemonTag> : null}
        {attributes.status ? <LemonTag type={statusToTag(attributes.status)}>{attributes.status}</LemonTag> : null}
        {attributes.lastRunAt ? (
            <LemonTag>
                Last run <TZLabel time={attributes.lastRunAt} />
            </LemonTag>
        ) : null}
    </div>
)

const NotebookNodePythonSettings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodePythonAttributes>): JSX.Element => {
    const { setTitlePlaceholder, toggleEditing } = useActions(notebookNodeLogic)

    const [draftCode, setDraftCode] = useState(attributes.code || DEFAULT_CODE)
    const { runCode, restartKernel, stopKernel, running, localError, setLocalError } = usePythonExecution(
        draftCode,
        attributes,
        updateAttributes
    )

    useEffect(() => {
        setTitlePlaceholder('Python')
    }, [setTitlePlaceholder])

    useEffect(() => {
        setDraftCode(attributes.code || DEFAULT_CODE)
    }, [attributes.code])

    const persistCode = useDebouncedCallback((nextCode: string) => {
        updateAttributes({ code: nextCode })
    }, 300)

    return (
        <div className="p-3 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
                <div className="flex flex-wrap items-center gap-1">
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        icon={<IconPlayFilled />}
                        loading={running}
                        onClick={() => runCode(draftCode)}
                    >
                        Run
                    </LemonButton>
                    <LemonButton size="xsmall" type="secondary" onClick={() => toggleEditing(false)}>
                        Collapse code
                    </LemonButton>
                    <LemonButton size="xsmall" icon={<IconRefresh />} onClick={restartKernel} disabled={running}>
                        Restart kernel
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        icon={<IconStopFilled />}
                        onClick={stopKernel}
                        disabled={running || !attributes.kernel}
                    >
                        Stop kernel
                    </LemonButton>
                </div>
                <PythonRunMeta attributes={attributes} />
            </div>

            {localError ? (
                <LemonBanner type="error" onClose={() => setLocalError(null)}>
                    {localError}
                </LemonBanner>
            ) : null}

            <div className="space-y-2">
                <CodeEditorInline
                    language="python"
                    height="240px"
                    value={draftCode}
                    onChange={(value) => {
                        setDraftCode(value)
                        persistCode(value)
                    }}
                    onPressCmdEnter={(value) => runCode(value ?? draftCode)}
                />
            </div>
        </div>
    )
}

export const NotebookNodePython = createPostHogWidgetNode<NotebookNodePythonAttributes>({
    nodeType: NotebookNodeType.Python,
    titlePlaceholder: 'Python',
    Component: NotebookNodePythonComponent,
    Settings: NotebookNodePythonSettings,
    heightEstimate: '26rem',
    minHeight: '16rem',
    resizeable: true,
    startExpanded: true,
    attributes: {
        code: { default: DEFAULT_CODE },
        stdout: { default: null },
        stderr: { default: null },
        result: { default: null },
        variables: { default: [] },
        status: { default: null },
        executionCount: { default: null },
        lastRunAt: { default: null },
        errorName: { default: null },
        traceback: { default: [] },
        kernel: { default: null },
    },
    serializedText: (attrs) => attrs.code || '',
})

export function buildPythonNodeContent(code?: string): JSONContent {
    return {
        type: NotebookNodeType.Python,
        attrs: { code: code || DEFAULT_CODE, __init: { expanded: true, showSettings: true } },
    }
}
