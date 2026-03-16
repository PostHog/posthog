import { useActions, useValues } from 'kea'
import { MouseEvent as ReactMouseEvent, ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { SQLEditor } from 'scenes/data-warehouse/editor/SQLEditor'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { nodeDetailSceneLogic } from '../nodeDetailSceneLogic'

const DEFAULT_EDITOR_HEIGHT = 500
const MIN_EDITOR_HEIGHT = 300

export function NodeDetailQuery({ id }: { id: string }): JSX.Element {
    const { savedQuery, savedQueryLoading } = useValues(nodeDetailSceneLogic({ id }))
    const queryString = savedQuery?.query?.query ?? ''

    const sqlEditorTabId = useMemo(() => `node-detail-query-${id}`, [id])
    const { setQueryInput, setSourceQuery, runQuery } = useActions(
        sqlEditorLogic({ tabId: sqlEditorTabId, mode: SQLEditorMode.Embedded })
    )

    useEffect(() => {
        if (queryString) {
            setQueryInput(queryString)
            setSourceQuery({
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: queryString,
                },
                display: ChartDisplayType.ActionsLineGraph,
            })
            runQuery(queryString)
        }
    }, [queryString]) // eslint-disable-line react-hooks/exhaustive-deps

    if (savedQueryLoading) {
        return (
            <ResizableSQLEditorContainer>
                <div className="flex items-center justify-center h-full">
                    <Spinner />
                </div>
            </ResizableSQLEditorContainer>
        )
    }

    if (!savedQuery) {
        return <div className="text-muted">No query available</div>
    }

    return (
        <ResizableSQLEditorContainer>
            <SQLEditor tabId={sqlEditorTabId} mode={SQLEditorMode.Embedded} />
        </ResizableSQLEditorContainer>
    )
}

function ResizableSQLEditorContainer({ children }: { children: ReactNode }): JSX.Element {
    const [height, setHeight] = useState(DEFAULT_EDITOR_HEIGHT)
    const containerRef = useRef<HTMLDivElement | null>(null)

    const startResizing = (event: ReactMouseEvent, startHeight: number): void => {
        event.preventDefault()
        const startY = event.clientY

        const onMouseMove = (moveEvent: MouseEvent): void => {
            setHeight(Math.max(MIN_EDITOR_HEIGHT, startHeight + (moveEvent.clientY - startY)))
        }

        const onMouseUp = (): void => {
            window.removeEventListener('mousemove', onMouseMove)
            window.removeEventListener('mouseup', onMouseUp)
        }

        window.addEventListener('mousemove', onMouseMove)
        window.addEventListener('mouseup', onMouseUp)
    }

    return (
        <div ref={containerRef} className="relative border rounded overflow-hidden" style={{ height }}>
            {children}
            <div
                className="absolute bottom-0 left-0 h-2 w-full cursor-s-resize"
                onMouseDown={(event) => {
                    startResizing(event, containerRef.current?.clientHeight ?? height)
                }}
            />
            <div
                className="absolute bottom-0 right-0 z-10 h-5 w-5 cursor-se-resize"
                onMouseDown={(event) => {
                    startResizing(event, containerRef.current?.clientHeight ?? height)
                }}
            />
        </div>
    )
}
