import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconPlayFilled, IconRefresh, IconStopFilled } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import api from 'lib/api'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { TZLabel } from 'lib/components/TZLabel'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'

import { notebookLogic } from '../Notebook/notebookLogic'
import {
    NotebookKernelExecutionResponse,
    NotebookKernelStatus,
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
    variables?: Record<string, string>
    status?: NotebookKernelExecutionResponse['status']
    executionCount?: number | null
    lastRunAt?: string | null
    errorName?: string | null
    traceback?: string[]
    kernel?: NotebookKernelStatus | null
    showVariables?: boolean
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
    const { setTitlePlaceholder } = useActions(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder('Python')
    }, [setTitlePlaceholder])

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
    const hasOutputs = Boolean(resultText || attributes.stdout || attributes.stderr || tracebackText)

    if (!expanded) {
        return null
    }

    return (
        <div className="space-y-2">
            <PythonRunMeta attributes={attributes} />

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
    const [showVariables, setShowVariables] = useState(attributes.showVariables ?? false)

    useEffect(() => {
        setTitlePlaceholder('Python')
    }, [setTitlePlaceholder])

    useEffect(() => {
        setDraftCode(attributes.code || DEFAULT_CODE)
    }, [attributes.code])

    useEffect(() => {
        setShowVariables(attributes.showVariables ?? false)
    }, [attributes.showVariables])

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
                variables: response.variables || {},
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

    const hasVariables = attributes.variables && Object.keys(attributes.variables).length > 0

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

            <div className="flex flex-col gap-3 md:flex-row">
                <div className="flex-1 space-y-2">
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
                <div className="w-full md:w-80 md:min-w-[18rem] flex-shrink-0 space-y-2 rounded border border-border p-2">
                    <div className="flex items-center justify-between gap-2">
                        <div className="text-xs font-semibold uppercase text-muted-alt">Variables</div>
                        <LemonSwitch
                            size="small"
                            checked={showVariables}
                            onChange={(checked) => {
                                setShowVariables(checked)
                                updateAttributes({ showVariables: checked })
                            }}
                            label="Debug"
                        />
                    </div>
                    {showVariables ? (
                        hasVariables ? (
                            <CodeSnippet language={Language.JSON} wrap compact>
                                {JSON.stringify(attributes.variables, null, 2)}
                            </CodeSnippet>
                        ) : (
                            <div className="text-xs text-muted-alt">No variables captured. Run code to populate.</div>
                        )
                    ) : (
                        <div className="text-xs text-muted-alt">
                            Toggle on to inspect variables alongside your code.
                        </div>
                    )}
                </div>
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
        variables: { default: {} },
        status: { default: null },
        executionCount: { default: null },
        lastRunAt: { default: null },
        errorName: { default: null },
        traceback: { default: [] },
        kernel: { default: null },
        showVariables: { default: false },
    },
    serializedText: (attrs) => attrs.code || '',
})

export function buildPythonNodeContent(code?: string): JSONContent {
    return {
        type: NotebookNodeType.Python,
        attrs: { code: code || DEFAULT_CODE },
    }
}
