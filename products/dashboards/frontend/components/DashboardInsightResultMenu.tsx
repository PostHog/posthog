import { useValues } from 'kea'
import { ReactNode, useId, useRef, useState } from 'react'

import { capturePersonsModalForClick, CapturedPersonsModal } from 'lib/components/ResultMenu/personsModalCapture'
import { ResultMenu } from 'lib/components/ResultMenu/ResultMenu'
import { objectsEqual } from 'lib/utils/objects'
import { getPersonsRecordingFilters } from 'scenes/trends/persons-modal/getPersonsRecordingFilters'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { urls } from 'scenes/urls'

import { DataTableNode, DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import {
    isActorsQuery,
    isBIVisualizationNode,
    isDataTableNode,
    isDataVisualizationNode,
    isHogQLQuery,
} from '~/queries/utils'
import { ChartDisplayType, InsightModel, ReplayTabs } from '~/types'

import { dashboardInsightResultMenuLogic } from './dashboardInsightResultMenuLogic'

export function DashboardInsightResultMenu({
    insight,
    children,
}: {
    insight: InsightModel
    children: ReactNode
}): JSX.Element {
    const [position, setPosition] = useState<{ x: number; y: number; timestamp: number } | null>(null)
    const [actors, setActors] = useState<CapturedPersonsModal | null>(null)
    const triggerRef = useRef<HTMLDivElement>(null)
    const captured = useRef(false)
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
    const { selectedResult: resolvedResult, resultLoading } = useValues(
        dashboardInsightResultMenuLogic({
            key: useId(),
            query: position && rowsQuery && isActorsQuery(rowsQuery.source) ? rowsQuery.source : null,
        })
    )
    const sqlUrl = resolvedResult?.sql
        ? urls.sqlEditor({ query: resolvedResult.sql })
        : sqlQuery
          ? urls.sqlEditor({ query: sqlQuery })
          : undefined
    const resultUnavailableReason = resultLoading
        ? 'Loading the selected result…'
        : 'Could not load the selected result. Select the data point again to retry.'
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
                if (
                    !event.currentTarget.contains(event.target as Node) ||
                    (event.target as Element).closest('a, input, select') ||
                    event.metaKey ||
                    event.ctrlKey ||
                    event.altKey ||
                    event.shiftKey
                ) {
                    return
                }
                captured.current = false
                const rect = (event.target as Element).getBoundingClientRect()
                const point = {
                    x: event.detail ? event.clientX : rect.x + rect.width / 2,
                    y: event.detail ? event.clientY : rect.y + rect.height / 2,
                    timestamp: event.timeStamp,
                }
                capturePersonsModalForClick((request) => {
                    captured.current = true
                    if (
                        position &&
                        actors &&
                        objectsEqual(actors.query, request.query) &&
                        objectsEqual(actors.rowsQuery, request.rowsQuery) &&
                        actors.url === request.url &&
                        actors.urlsIndex === request.urlsIndex &&
                        objectsEqual(actors.urls, request.urls)
                    ) {
                        close()
                        return
                    }
                    setActors(request)
                    setPosition(point)
                })
            }}
            onClick={(event) => {
                if (
                    !event.currentTarget.contains(event.target as Node) ||
                    captured.current ||
                    (event.target as Element).closest('a, button, input, select, [role="button"]') ||
                    event.metaKey ||
                    event.ctrlKey ||
                    event.altKey ||
                    event.shiftKey
                ) {
                    return
                }
                if (position) {
                    close()
                    return
                }
                setActors(null)
                setPosition({ x: event.clientX, y: event.clientY, timestamp: event.timeStamp })
            }}
        >
            {children}
            {position && (
                <ResultMenu
                    triggerRef={triggerRef}
                    selectedResult={selectedResult}
                    caption={actors ? insight.name || 'Insight result' : 'Dashboard insight'}
                    interaction={position}
                    close={close}
                    actions={[
                        {
                            name: sqlQuery ? 'View underlying rows' : 'View people',
                            className: 'ResultMenu__rows',
                            to: rowsUrl,
                            inPlace: !!actors,
                            disabledReason:
                                !actors && !sqlQuery
                                    ? 'Select a data point to view the users or groups behind it.'
                                    : undefined,
                            onClick: () => {
                                const request = actors
                                close()
                                if (request) {
                                    request.open ? request.open() : openPersonsModal(request)
                                }
                            },
                        },
                        ...(canViewRecordings && recordingQuery
                            ? [
                                  {
                                      name: 'View recordings',
                                      className: 'ResultMenu__recordings',
                                      to: resolvedResult?.sessionIds.length
                                          ? urls.replay(
                                                ReplayTabs.Home,
                                                getPersonsRecordingFilters(
                                                    { kind: NodeKind.ActorsQuery, source: recordingQuery },
                                                    resolvedResult.sessionIds
                                                )
                                            )
                                          : undefined,
                                      disabledReason: resolvedResult?.sessionIds.length
                                          ? undefined
                                          : resolvedResult
                                            ? 'No recordings found for this result.'
                                            : resultUnavailableReason,
                                      onClick: close,
                                  },
                              ]
                            : []),
                        {
                            name: 'Open in SQL editor',
                            className: 'ResultMenu__sql',
                            to: sqlUrl,
                            disabledReason: sqlUrl
                                ? undefined
                                : actors
                                  ? resultUnavailableReason
                                  : 'Select a data point to edit its underlying query.',
                            onClick: close,
                        },
                    ]}
                />
            )}
        </div>
    )
}
