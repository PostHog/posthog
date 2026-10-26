import { ReactNode, useRef, useState } from 'react'

import { IconCode, IconRewindPlay } from '@posthog/icons'

import { capturePersonsModalForClick, CapturedPersonsModal } from 'lib/components/ResultMenu/personsModalCapture'
import { ResultMenu } from 'lib/components/ResultMenu/ResultMenu'
import { IconTableChart } from 'lib/lemon-ui/icons'
import { objectsEqual } from 'lib/utils/objects'
import { getPersonsRecordingFilters } from 'scenes/trends/persons-modal/getPersonsRecordingFilters'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { urls } from 'scenes/urls'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { isBIVisualizationNode, isDataVisualizationNode, isDataTableNode, isHogQLQuery } from '~/queries/utils'
import { ChartDisplayType, InsightModel, ReplayTabs } from '~/types'

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
    const sqlQuery =
        query &&
        (isDataVisualizationNode(query) ||
            isBIVisualizationNode(query) ||
            (isDataTableNode(query) && isHogQLQuery(query.source)))
            ? query
            : undefined
    const rowsQuery: DataTableNode | undefined =
        actors?.rowsQuery ??
        (actors?.query
            ? {
                  kind: NodeKind.DataTableNode,
                  source: {
                      kind: NodeKind.ActorsQuery,
                      source: actors.query,
                      select: ['actor', ...Object.values(actors.additionalSelect || {})],
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
    const recordingQuery = actors?.query
    const canViewRecordings =
        !!recordingQuery &&
        (('includeRecordings' in recordingQuery && recordingQuery.includeRecordings) ||
            !!actors?.additionalSelect?.matched_recordings)
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
                            icon: <IconTableChart />,
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
                        {
                            name: 'Open in SQL editor',
                            icon: <IconCode />,
                            className: 'ResultMenu__sql',
                            to: rowsQuery || sqlQuery ? urls.sqlEditor({ query: rowsQuery ?? sqlQuery }) : undefined,
                            disabledReason:
                                rowsQuery || sqlQuery ? undefined : 'Select a data point to edit its underlying query.',
                            onClick: close,
                        },
                        ...(canViewRecordings && recordingQuery
                            ? [
                                  {
                                      name: 'View recordings',
                                      icon: <IconRewindPlay />,
                                      className: 'ResultMenu__recordings',
                                      to: urls.replay(
                                          ReplayTabs.Home,
                                          getPersonsRecordingFilters(
                                              {
                                                  kind: NodeKind.ActorsQuery,
                                                  source: recordingQuery,
                                              },
                                              []
                                          )
                                      ),
                                      onClick: close,
                                  },
                              ]
                            : []),
                    ]}
                />
            )}
        </div>
    )
}
