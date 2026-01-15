import clsx from 'clsx'
import { useMountedLogic, useValues } from 'kea'
import { useLayoutEffect, useMemo, useRef } from 'react'

import { IconCornerDownRight } from '@posthog/icons'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'
import { PythonExecutionMedia, PythonExecutionResult } from './pythonExecution'
import { renderAnsiText } from './utils'

export type NotebookNodeDuckSQLAttributes = {
    code: string
    returnVariable: string
    duckExecution?: PythonExecutionResult | null
    duckExecutionCodeHash?: number | null
    showSettings?: boolean
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

const buildMediaSource = (media: PythonExecutionMedia): string | null => {
    if (media.mimeType === 'image/png') {
        return `data:image/png;base64,${media.data}`
    }
    if (media.mimeType === 'image/jpeg') {
        return `data:image/jpeg;base64,${media.data}`
    }
    if (media.mimeType === 'image/svg+xml') {
        return `data:image/svg+xml;utf8,${encodeURIComponent(media.data)}`
    }
    return null
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
                alt="Duck SQL output"
                className="mt-2 max-w-full border border-border rounded bg-bg-light"
            />
        </div>
    )
}

const DEFAULT_DUCK_SQL_NODE_HEIGHT = 100
const MAX_DUCK_SQL_NODE_HEIGHT = 500

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodeDuckSQLAttributes>): JSX.Element | null => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded } = useValues(nodeLogic)
    const outputRef = useRef<HTMLDivElement | null>(null)
    const footerRef = useRef<HTMLDivElement | null>(null)

    const duckExecution = attributes.duckExecution ?? null
    const hasResult = duckExecution?.result !== undefined && duckExecution?.result !== null
    const hasExecution =
        duckExecution &&
        (duckExecution.stdout ||
            duckExecution.stderr ||
            hasResult ||
            duckExecution.media?.length ||
            duckExecution.traceback?.length)

    useLayoutEffect(() => {
        if (!hasExecution) {
            return
        }
        const output = outputRef.current
        if (!output) {
            return
        }
        const footerHeight = footerRef.current?.offsetHeight ?? 0
        const desiredHeight = Math.min(MAX_DUCK_SQL_NODE_HEIGHT, output.scrollHeight + footerHeight)
        const currentHeight = typeof attributes.height === 'number' ? attributes.height : DEFAULT_DUCK_SQL_NODE_HEIGHT

        if (desiredHeight > currentHeight) {
            updateAttributes({ height: desiredHeight })
        }
    }, [
        attributes.height,
        duckExecution?.media?.length,
        duckExecution?.result,
        duckExecution?.stderr,
        duckExecution?.stdout,
        duckExecution?.traceback?.length,
        hasExecution,
        updateAttributes,
    ])

    const isSettingsVisible = attributes.showSettings ?? false
    const showReturnVariableRow = expanded || isSettingsVisible

    if (!expanded && !showReturnVariableRow) {
        return null
    }

    return (
        <div data-attr="notebook-node-duck-sql" className="flex h-full flex-col gap-2">
            {expanded ? (
                <div ref={outputRef} className="p-3 overflow-y-auto h-full space-y-3">
                    {hasExecution ? (
                        <>
                            {duckExecution?.stdout ? (
                                <OutputBlock title="Output" toneClassName="text-default" value={duckExecution.stdout} />
                            ) : null}
                            {duckExecution?.stderr ? (
                                <OutputBlock title="stderr" toneClassName="text-danger" value={duckExecution.stderr} />
                            ) : null}
                            {hasResult ? (
                                <OutputBlock title="Result" toneClassName="text-default" value={duckExecution.result} />
                            ) : null}
                            {duckExecution?.media?.map((media, index) => (
                                <MediaBlock key={`duck-sql-media-${index}`} media={media} />
                            ))}
                            {duckExecution?.status === 'error' && duckExecution.traceback?.length ? (
                                <OutputBlock
                                    title="Error"
                                    toneClassName="text-danger"
                                    value={duckExecution.traceback.join('\n')}
                                />
                            ) : null}
                        </>
                    ) : (
                        <div className="text-xs text-muted font-mono">Run the query to see execution results.</div>
                    )}
                </div>
            ) : null}
            {showReturnVariableRow ? (
                <div
                    ref={footerRef}
                    className="flex items-center gap-2 text-xs text-muted border-t p-2"
                    onClick={(event) => event.stopPropagation()}
                    onMouseDown={(event) => event.stopPropagation()}
                >
                    <span className="font-mono mt-0.5">
                        <IconCornerDownRight />
                    </span>
                    <input
                        type="text"
                        className="rounded border border-border px-1.5 py-0.5 text-xs font-mono bg-bg-light text-default focus:outline-none focus:ring-1 focus:ring-primary"
                        value={attributes.returnVariable ?? ''}
                        onChange={(event) => updateAttributes({ returnVariable: event.target.value })}
                        spellCheck={false}
                    />
                </div>
            ) : null}
        </div>
    )
}

const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeDuckSQLAttributes>): JSX.Element => {
    return (
        <CodeEditorResizeable
            language="sql"
            value={attributes.code}
            onChange={(value) => updateAttributes({ code: value ?? '' })}
            allowManualResize={false}
            minHeight={160}
            embedded
        />
    )
}

export const NotebookNodeDuckSQL = createPostHogWidgetNode<NotebookNodeDuckSQLAttributes>({
    nodeType: NotebookNodeType.DuckSQL,
    titlePlaceholder: 'Duck SQL',
    Component,
    heightEstimate: 120,
    minHeight: 80,
    resizeable: true,
    startExpanded: true,
    attributes: {
        code: {
            default: '',
        },
        returnVariable: {
            default: 'duck_df',
        },
        duckExecution: {
            default: null,
        },
        duckExecutionCodeHash: {
            default: null,
        },
        showSettings: {
            default: false,
        },
    },
    Settings,
    settingsPlacement: 'inline',
    serializedText: (attrs) => attrs.code,
})
