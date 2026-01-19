import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useLayoutEffect, useMemo, useRef, useState } from 'react'

import { IconCornerDownRight } from '@posthog/icons'

import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { NotebookDataframeTable } from './components/NotebookDataframeTable'
import type { NotebookDependencyUsage } from './notebookNodeContent'
import { notebookNodeLogic } from './notebookNodeLogic'
import { PythonExecutionMedia, PythonExecutionResult } from './pythonExecution'
import { buildMediaSource, renderAnsiText } from './utils'

export type NotebookNodePythonAttributes = {
    code: string
    globalsUsed?: string[]
    globalsExportedWithTypes?: { name: string; type: string }[]
    globalsAnalysisHash?: string | null
    pythonExecution?: PythonExecutionResult | null
    pythonExecutionCodeHash?: number | null
    pythonExecutionSandboxId?: string | null
    showSettings?: boolean
    autoHeight?: boolean
}

const VariableUsageOverlay = ({
    name,
    type,
    usages,
    onNavigateToNode,
}: {
    name: string
    type: string
    usages: NotebookDependencyUsage[]
    onNavigateToNode?: (nodeId: string) => void
}): JSX.Element => {
    const groupedUsageEntries = usages.reduce<Record<string, NotebookDependencyUsage>>((acc, usage) => {
        if (!acc[usage.nodeId]) {
            acc[usage.nodeId] = usage
        }
        return acc
    }, {})
    const sortedUsageEntries = Object.values(groupedUsageEntries).sort((a, b) => a.nodeIndex - b.nodeIndex)

    const usageLabel = (usage: NotebookDependencyUsage): string => {
        const trimmedTitle = usage.title.trim()
        return trimmedTitle ? trimmedTitle : `Python cell ${usage.nodeIndex}`
    }

    return (
        <div className="p-2 text-xs max-w-[320px]">
            <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-default font-mono">{name}</span>
                <span className="text-muted">Type: {type || 'unknown'}</span>
            </div>
            {sortedUsageEntries.length > 0 ? (
                <div className="mt-2">
                    <div className="text-muted text-[10px] uppercase tracking-wide">Used in</div>
                    <div className="mt-1 space-y-1 max-h-48 overflow-y-auto">
                        {sortedUsageEntries.map((usage) => (
                            <div key={`usage-${usage.nodeIndex}`}>
                                {onNavigateToNode ? (
                                    <button
                                        type="button"
                                        className="text-muted hover:text-default underline underline-offset-2"
                                        onClick={() => onNavigateToNode(usage.nodeId)}
                                    >
                                        {usageLabel(usage)}
                                    </button>
                                ) : (
                                    <div className="text-muted">{usageLabel(usage)}</div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            ) : (
                <div className="mt-2 text-muted">Not used in later cells.</div>
            )}
        </div>
    )
}

const VariableDependencyBadge = ({
    name,
    type,
    usages,
    onNavigateToNode,
}: {
    name: string
    type: string
    usages: NotebookDependencyUsage[]
    onNavigateToNode?: (nodeId: string) => void
}): JSX.Element => {
    const [popoverVisible, setPopoverVisible] = useState(false)
    const isUsedDownstream = usages.length > 0

    return (
        <Popover
            onClickOutside={() => setPopoverVisible(false)}
            visible={popoverVisible}
            placement="bottom-start"
            overlay={
                <VariableUsageOverlay
                    name={name}
                    type={type}
                    usages={usages}
                    onNavigateToNode={(nodeId) => {
                        onNavigateToNode?.(nodeId)
                        setPopoverVisible(false)
                    }}
                />
            }
        >
            <button
                type="button"
                onClick={() => setPopoverVisible((visible) => !visible)}
                className="rounded border border-border px-1.5 py-0.5 text-xs font-mono bg-bg-light text-default hover:bg-bg-light/80 transition"
            >
                <span className={isUsedDownstream ? 'font-semibold' : undefined}>{name}</span>
                {isUsedDownstream ? <span className="text-muted"> → {usages.length}</span> : null}
            </button>
        </Popover>
    )
}

const OutputBlock = ({
    title,
    toneClassName,
    value,
}: {
    title: string
    toneClassName: string
    value: string
}): JSX.Element => {
    const content = useMemo(() => renderAnsiText(value), [value])

    return (
        <div>
            <div className="text-[10px] uppercase tracking-wide text-muted">{title}</div>
            <pre
                className={clsx('text-xs font-mono whitespace-pre-wrap mt-1 select-text cursor-text', toneClassName)}
                contentEditable={false}
            >
                {content}
            </pre>
        </div>
    )
}

const MediaBlock = ({ media }: { media: PythonExecutionMedia }): JSX.Element | null => {
    const source = buildMediaSource(media)
    if (!source) {
        return null
    }

    return (
        <div>
            <div className="text-[10px] uppercase tracking-wide text-muted">Image</div>
            <img
                src={source}
                alt="Python output"
                className="mt-2 max-w-full border border-border rounded bg-bg-light"
            />
        </div>
    )
}

const DEFAULT_PYTHON_NODE_HEIGHT = 100
const MAX_PYTHON_NODE_HEIGHT = 500

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodePythonAttributes>): JSX.Element | null => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const {
        dataframePage,
        dataframePageSize,
        dataframeLoading,
        dataframeResult,
        dataframeVariableName,
        displayedGlobals,
        expanded,
        exportedGlobals,
        pythonExecution,
        usageByVariable,
    } = useValues(nodeLogic)
    const { navigateToNode, setDataframePage, setDataframePageSize } = useActions(nodeLogic)
    const outputRef = useRef<HTMLDivElement | null>(null)
    const footerRef = useRef<HTMLDivElement | null>(null)

    const hasResult = pythonExecution?.result !== undefined && pythonExecution?.result !== null
    const hasExecution =
        pythonExecution &&
        (pythonExecution.stdout ||
            pythonExecution.stderr ||
            hasResult ||
            pythonExecution.media?.length ||
            pythonExecution.traceback?.length ||
            pythonExecution.variables?.length)

    useLayoutEffect(() => {
        if (!hasExecution || attributes.autoHeight === false) {
            return
        }
        const output = outputRef.current
        if (!output) {
            return
        }
        const footerHeight = footerRef.current?.offsetHeight ?? 0
        const desiredHeight = Math.min(MAX_PYTHON_NODE_HEIGHT, output.scrollHeight + footerHeight)
        const currentHeight = typeof attributes.height === 'number' ? attributes.height : DEFAULT_PYTHON_NODE_HEIGHT

        if (desiredHeight !== currentHeight) {
            updateAttributes({ height: desiredHeight })
        }
    }, [
        attributes.height,
        hasExecution,
        pythonExecution?.media?.length,
        pythonExecution?.result,
        pythonExecution?.stderr,
        pythonExecution?.stdout,
        pythonExecution?.traceback?.length,
        pythonExecution?.variables?.length,
        updateAttributes,
    ])

    if (!expanded) {
        return null
    }
    const showDataframeTable = !!dataframeVariableName

    return (
        <div data-attr="notebook-node-python" className="flex h-full flex-col gap-2">
            <div
                ref={outputRef}
                className="p-2 overflow-y-auto h-full space-y-3"
                onMouseDown={(event) => event.stopPropagation()}
                onDragStart={(event) => event.stopPropagation()}
            >
                {hasExecution ? (
                    <>
                        {pythonExecution?.stdout ? (
                            <OutputBlock
                                title="Output"
                                toneClassName="text-default"
                                value={pythonExecution.stdout ?? ''}
                            />
                        ) : null}
                        {pythonExecution?.stderr ? (
                            <OutputBlock
                                title="stderr"
                                toneClassName="text-danger"
                                value={pythonExecution.stderr ?? ''}
                            />
                        ) : null}
                        {hasResult && !showDataframeTable ? (
                            <OutputBlock
                                title="Result"
                                toneClassName="text-default"
                                value={pythonExecution.result ?? ''}
                            />
                        ) : null}
                        {showDataframeTable ? (
                            <NotebookDataframeTable
                                result={dataframeResult}
                                loading={dataframeLoading}
                                page={dataframePage}
                                pageSize={dataframePageSize}
                                onNextPage={() => setDataframePage(dataframePage + 1)}
                                onPreviousPage={() => setDataframePage(Math.max(1, dataframePage - 1))}
                                onPageSizeChange={setDataframePageSize}
                            />
                        ) : null}
                        {pythonExecution?.media?.map((media, index) => (
                            <MediaBlock key={`python-media-${index}`} media={media} />
                        ))}
                        {pythonExecution?.status === 'error' && pythonExecution.traceback?.length ? (
                            <OutputBlock
                                title="Error"
                                toneClassName="text-danger"
                                value={pythonExecution.traceback.join('\n')}
                            />
                        ) : null}
                    </>
                ) : (
                    <div className="text-xs text-muted font-mono">Run the cell to see execution results.</div>
                )}
            </div>
            {exportedGlobals.length > 0 ? (
                <div ref={footerRef} className="flex items-start flex-wrap gap-2 text-xs text-muted border-t p-2">
                    <span className="font-mono mt-1">
                        <IconCornerDownRight />
                    </span>
                    <div className="flex flex-wrap gap-1">
                        {displayedGlobals.map(({ name, type }) => (
                            <VariableDependencyBadge
                                key={name}
                                name={name}
                                type={type}
                                usages={usageByVariable[name] ?? []}
                                onNavigateToNode={navigateToNode}
                            />
                        ))}
                    </div>
                </div>
            ) : null}
        </div>
    )
}

const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodePythonAttributes>): JSX.Element => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { runPythonNodeWithMode } = useActions(nodeLogic)

    return (
        <CodeEditorResizeable
            language="python"
            value={attributes.code}
            onChange={(value) => updateAttributes({ code: value ?? '' })}
            onPressCmdEnter={() => {
                void runPythonNodeWithMode({ mode: 'auto' })
            }}
            allowManualResize={false}
            minHeight={160}
            embedded
        />
    )
}

export const NotebookNodePython = createPostHogWidgetNode<NotebookNodePythonAttributes>({
    nodeType: NotebookNodeType.Python,
    titlePlaceholder: 'Python',
    Component,
    heightEstimate: 120,
    minHeight: 80,
    resizeable: true,
    startExpanded: true,
    attributes: {
        code: {
            default: '',
        },
        globalsUsed: {
            default: [],
        },
        globalsExportedWithTypes: {
            default: [],
        },
        globalsAnalysisHash: {
            default: null,
        },
        pythonExecution: {
            default: null,
        },
        pythonExecutionCodeHash: {
            default: null,
        },
        pythonExecutionSandboxId: {
            default: null,
        },
        showSettings: {
            default: false,
        },
        autoHeight: {
            default: true,
        },
    },
    Settings,
    settingsPlacement: 'inline',
    serializedText: (attrs) => attrs.code,
})
