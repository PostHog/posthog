import { useActions, useValues } from 'kea'
import { ComponentProps, useCallback, useEffect, useMemo, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconPlayFilled, IconRefresh, IconStopFilled } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'

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

const NotebookNodePythonComponent = ({
    attributes,
}: NotebookNodeProps<NotebookNodePythonAttributes>): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)
    const { editingNodeId } = useValues(notebookLogic)
    const { setTitlePlaceholder } = useActions(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder('Python')
    }, [setTitlePlaceholder])

    const variables = attributes.variables || []
    const hasVariables = variables.length > 0
    const hasRun = attributes.executionCount !== null && attributes.executionCount !== undefined
    const isEditingThisNode = editingNodeId === attributes.nodeId

    const resultText = useMemo(() => {
        if (!attributes.result) {
            return null
        }

        const textResult = attributes.result['text/plain']
        if (typeof textResult === 'string') {
            return textResult
        }

        return JSON.stringify(attributes.result, null, 2)
    }, [attributes.result])

    const tracebackText = useMemo(() => (attributes.traceback || []).join('\n'), [attributes.traceback])
    const hasOutputs = Boolean(
        resultText || attributes.stdout || attributes.stderr || tracebackText || hasVariables || hasRun
    )

    if (!expanded) {
        return null
    }

    return (
        <div className="space-y-2">
            {hasOutputs && !isEditingThisNode ? (
                <div className="flex justify-end">
                    <PythonRunMeta attributes={attributes} />
                </div>
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
                    {attributes.stdout ? (
                        <OutputBlock title="Stdout">
                            <CodeSnippet language={Language.Text} wrap compact>
                                {attributes.stdout}
                            </CodeSnippet>
                        </OutputBlock>
                    ) : null}
                    {attributes.stderr ? (
                        <OutputBlock title="Stderr">
                            <CodeSnippet language={Language.Text} wrap compact>
                                {attributes.stderr}
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
                            <VariablesOutput variables={variables} hasRun={hasRun} />
                        </OutputBlock>
                    ) : null}
                </div>
            ) : (
                <LemonBanner type="info">
                    Use Filters to edit and run your Python code. Results will appear here once the code runs.
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
    if (!variables.length) {
        return (
            <div className="text-xs text-muted-alt">
                {hasRun ? 'No variables captured yet.' : 'Run code to populate variables.'}
            </div>
        )
    }

    return (
        <div className="space-y-1">
            {variables.map((variable) => {
                const kindMeta = VARIABLE_KIND_META[variable.kind] || VARIABLE_KIND_META.scalar

                return (
                    <div
                        key={variable.name}
                        className="flex flex-col gap-1 rounded border border-border p-2"
                        title={variable.module || undefined}
                    >
                        <div className="flex flex-wrap items-center gap-2">
                            <code className="text-xs font-semibold leading-tight">{variable.name}</code>
                            <LemonTag type={kindMeta.tag} size="small">
                                {kindMeta.label}
                            </LemonTag>
                            <span className="text-xs text-muted-alt">{variable.type}</span>
                        </div>
                        <div className="text-xs font-mono text-muted-alt whitespace-pre-wrap break-words leading-tight">
                            {variable.repr}
                        </div>
                    </div>
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
    const { shortId } = useValues(notebookLogic)
    const { setTitlePlaceholder } = useActions(notebookNodeLogic)

    const [draftCode, setDraftCode] = useState(attributes.code || DEFAULT_CODE)
    const [running, setRunning] = useState(false)
    const [localError, setLocalError] = useState<string | null>(null)

    useEffect(() => {
        setTitlePlaceholder('Python')
    }, [setTitlePlaceholder])

    useEffect(() => {
        setDraftCode(attributes.code || DEFAULT_CODE)
    }, [attributes.code])

    const persistCode = useDebouncedCallback((nextCode: string) => {
        updateAttributes({ code: nextCode })
    }, 300)

    const handleExecution = useCallback(
        (response: NotebookKernelExecutionResponse) => {
            updateAttributes({
                code: draftCode,
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
        [draftCode, updateAttributes]
    )

    const runCode = useCallback(async () => {
        setRunning(true)
        setLocalError(null)
        try {
            const response = await api.notebooks.executeKernel(shortId, {
                code: draftCode,
                return_variables: true,
            })
            handleExecution(response)
        } catch (error: any) {
            setLocalError(error?.message ?? 'Unable to run code')
        } finally {
            setRunning(false)
        }
    }, [draftCode, handleExecution, shortId])

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

    return (
        <div className="p-3 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-1">
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        icon={<IconPlayFilled />}
                        loading={running}
                        onClick={runCode}
                    >
                        Run
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

            {localError ? <LemonBanner type="error">{localError}</LemonBanner> : null}

            <div className="space-y-2">
                <CodeEditorInline
                    language="python"
                    height="240px"
                    value={draftCode}
                    onChange={(value) => {
                        setDraftCode(value)
                        persistCode(value)
                    }}
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
        attrs: { code: code || DEFAULT_CODE },
    }
}
