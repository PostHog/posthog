import { ReactNode, useId, useRef, useState } from 'react'

import { capturePersonsModalForClick, CapturedPersonsModal } from 'lib/components/ResultMenu/personsModalCapture'
import {
    getResultMenuPoint,
    isResultMenuContextMenu,
    replayAsClick,
    ResultMenuPoint,
} from 'lib/components/ResultMenu/resultMenuTrigger'
import { urls } from 'scenes/urls'

import { DataTableNode, DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { isBIVisualizationNode, isDataTableNode, isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'
import { ChartDisplayType, InsightModel } from '~/types'

import { DashboardInsightResultMenuPopover } from './DashboardInsightResultMenuPopover'

export function DashboardInsightResultMenu({
    insight,
    children,
}: {
    insight: InsightModel
    children: ReactNode
}): JSX.Element {
    const [position, setPosition] = useState<ResultMenuPoint | null>(null)
    const [actors, setActors] = useState<CapturedPersonsModal | null>(null)
    // Each opened menu loads its result again, so selecting the same point again retries a failed load.
    const [selection, setSelection] = useState(0)
    const menuId = useId()
    const triggerRef = useRef<HTMLDivElement>(null)
    const captured = useRef(false)
    const replaying = useRef(false)
    const open = (point: ResultMenuPoint, request: CapturedPersonsModal | null): void => {
        setActors(request)
        setPosition(point)
        setSelection((current) => current + 1)
    }
    const close = (): void => {
        setPosition(null)
        setActors(null)
    }
    const query = insight.query
    const sqlQuery: DataVisualizationNode | DataTableNode | undefined =
        query && isBIVisualizationNode(query)
            ? {
                  kind: NodeKind.DataVisualizationNode,
                  source: query.source,
                  display: ChartDisplayType.ActionsTable,
              }
            : query &&
                ((isDataVisualizationNode(query) && query.kind === NodeKind.DataVisualizationNode) ||
                    (isDataTableNode(query) && isHogQLQuery(query.source)))
              ? query
              : undefined
    const recordingQuery = actors?.query
    const canViewRecordings = !!recordingQuery && !!actors?.additionalSelect?.matched_recordings
    const rowsQuery: DataTableNode | undefined =
        actors?.rowsQuery ??
        (actors?.query
            ? {
                  kind: NodeKind.DataTableNode,
                  source: {
                      kind: NodeKind.ActorsQuery,
                      source: actors.query,
                      select: [
                          ...new Set([
                              'actor',
                              ...Object.values(actors.additionalSelect || {}),
                              ...(canViewRecordings ? ['matched_recordings'] : []),
                          ]),
                      ],
                      orderBy: actors.orderBy,
                  },
                  full: true,
              }
            : undefined)
    const rowsUrl = rowsQuery
        ? urls.insightNew({ query: rowsQuery })
        : sqlQuery
          ? urls.sqlEditor({
                query: isDataTableNode(sqlQuery) ? sqlQuery : { ...sqlQuery, display: ChartDisplayType.ActionsTable },
            })
          : undefined
    const selectedResult = actors?.title
        ? typeof actors.title === 'function'
            ? actors.title('Results')
            : actors.title
        : insight.name || 'Untitled insight'
    return (
        <div
            ref={triggerRef}
            className="flex flex-1 flex-col min-h-0 h-full"
            onClickCapture={(event) => {
                if (position && !replaying.current && event.currentTarget.contains(event.target as Node)) {
                    close()
                }
            }}
            onContextMenuCapture={(event) => {
                if (!isResultMenuContextMenu(event)) {
                    return
                }
                captured.current = false
                const point = getResultMenuPoint(event)
                capturePersonsModalForClick((request) => {
                    captured.current = true
                    open(point, request)
                })
            }}
            onContextMenu={(event) => {
                if (!isResultMenuContextMenu(event)) {
                    return
                }
                event.preventDefault()
                // A chart with `onPointContextMenu` captures its result before this handler runs.
                if (!captured.current) {
                    replaying.current = true
                    try {
                        replayAsClick(event)
                    } finally {
                        replaying.current = false
                    }
                }
                if (!captured.current) {
                    open(getResultMenuPoint(event), null)
                }
            }}
        >
            {children}
            {position && (
                <DashboardInsightResultMenuPopover
                    logicKey={`${menuId}-${selection}`}
                    triggerRef={triggerRef}
                    position={position}
                    selectedResult={selectedResult}
                    caption={actors ? insight.name || 'Insight result' : 'Dashboard insight'}
                    actors={actors}
                    canViewRecordings={canViewRecordings}
                    sqlQuery={sqlQuery}
                    rowsQuery={rowsQuery}
                    rowsUrl={rowsUrl}
                    close={close}
                />
            )}
        </div>
    )
}
