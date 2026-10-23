import { useActions, useValues } from 'kea'
import { ReactNode, useCallback, useMemo, useRef, useState } from 'react'

import { IconCode, IconExternal, IconFilter } from '@posthog/icons'
import type { PointClickData } from '@posthog/quill-charts'

import { capturePersonsModalForClick, CapturedPersonsModal } from 'lib/components/ResultMenu/personsModalCapture'
import { ResultChartSelectionContext, ResultChartPoint } from 'lib/components/ResultMenu/resultChartSelection'
import { ResultMenu } from 'lib/components/ResultMenu/ResultMenu'
import { IconTableChart } from 'lib/lemon-ui/icons'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { urls } from 'scenes/urls'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { isBIVisualizationNode, isDataVisualizationNode } from '~/queries/utils'
import { ChartDisplayType, InsightModel } from '~/types'

import { biDashboardCrossFilterLogic } from 'products/business_intelligence/frontend/biDashboardCrossFilterLogic'

import { dashboardResultFilterLogic } from '../dashboardResultFilterLogic'
import {
    DashboardResultSelection,
    getDashboardResultActors,
    getDashboardResultFilterLink,
} from '../dashboardResultFilters'

export function DashboardInsightResultMenu({
    insight,
    children,
    dashboardId,
    tileId,
}: {
    insight: InsightModel
    children: ReactNode
    dashboardId?: number
    tileId?: number
}): JSX.Element {
    const { selection: dashboardSelection } = useValues(dashboardResultFilterLogic({ dashboardId: dashboardId ?? 0 }))
    const { selectResult } = useActions(dashboardResultFilterLogic({ dashboardId: dashboardId ?? 0 }))
    const [position, setPosition] = useState<{ x: number; y: number; timestamp: number } | null>(null)
    const [actors, setActors] = useState<CapturedPersonsModal | null>(null)
    const captured = useRef(false)
    const clickedPoint = useRef<ResultChartPoint>()
    const capturePoint = useCallback((point: PointClickData): void => {
        clickedPoint.current = { seriesKey: point.series.key, label: point.label }
    }, [])
    const captureCell = useCallback((point: ResultChartPoint): void => {
        clickedPoint.current = point
    }, [])
    const chartSelection = useMemo(
        () => ({
            capturePoint,
            captureCell,
            point: dashboardSelection?.tileId === tileId ? dashboardSelection?.chartPoint : undefined,
        }),
        [capturePoint, captureCell, dashboardSelection, tileId]
    )
    const close = (): void => {
        setPosition(null)
        setActors(null)
    }
    const getSelection = (request: CapturedPersonsModal): DashboardResultSelection | null => {
        const query = getDashboardResultActors(request)
        const title = typeof request.title === 'function' ? request.title('Users / groups') : request.title
        return dashboardId && tileId && query
            ? {
                  dashboardId,
                  tileId,
                  query,
                  chartPoint: clickedPoint.current,
                  label: typeof title === 'string' ? title : insight.name || 'Selected result',
              }
            : null
    }
    const filterResult = (selection: DashboardResultSelection): void => {
        biDashboardCrossFilterLogic.findMounted({ dashboardId: selection.dashboardId })?.actions.setSelection(null)
        selectResult(selection)
        close()
    }
    const selectedFilter = actors ? getSelection(actors) : null
    const query = insight.query
    const sqlQuery = query && (isDataVisualizationNode(query) || isBIVisualizationNode(query)) ? query : undefined
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
          ? urls.sqlEditor({ query: { ...sqlQuery, display: ChartDisplayType.ActionsTable } })
          : undefined
    const selectedResult = actors?.title
        ? typeof actors.title === 'function'
            ? actors.title('Results')
            : actors.title
        : insight.name || 'Untitled insight'
    return (
        <div
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
                clickedPoint.current = undefined
                const rect = (event.target as Element).getBoundingClientRect()
                const point = {
                    x: event.detail ? event.clientX : rect.x + rect.width / 2,
                    y: event.detail ? event.clientY : rect.y + rect.height / 2,
                    timestamp: event.timeStamp,
                }
                capturePersonsModalForClick((request) => {
                    captured.current = true
                    const selection = getSelection(request)
                    if (selection && (dashboardSelection || event.detail === 2)) {
                        filterResult(selection)
                        return
                    }
                    if (event.detail === 2) {
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
                if (position || event.detail === 2) {
                    close()
                    return
                }
                setActors(null)
                setPosition({ x: event.clientX, y: event.clientY, timestamp: event.timeStamp })
            }}
        >
            <ResultChartSelectionContext.Provider value={chartSelection}>
                {children}
            </ResultChartSelectionContext.Provider>
            {position && (
                <ResultMenu
                    selectedResult={selectedResult}
                    caption={actors ? insight.name || 'Insight result' : 'Dashboard insight'}
                    interaction={position}
                    close={close}
                    canFilter={!!selectedFilter}
                    actions={[
                        ...(selectedFilter
                            ? [
                                  {
                                      name: 'Filter dashboard by this result',
                                      icon: <IconFilter />,
                                      className: 'BIDrilldownMenu__filter',
                                      to: getDashboardResultFilterLink(selectedFilter),
                                      inPlace: true,
                                      onClick: () => filterResult(selectedFilter),
                                  },
                              ]
                            : []),
                        {
                            name: rowsQuery ? 'Explore in new insight' : 'Open insight',
                            icon: <IconExternal />,
                            className: 'BIDrilldownMenu__worksheet',
                            to: rowsQuery ? rowsUrl : urls.insightView(insight.short_id),
                            onClick: close,
                        },
                        {
                            name: 'View underlying rows',
                            icon: <IconTableChart />,
                            className: 'BIDrilldownMenu__rows',
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
                            className: 'BIDrilldownMenu__sql',
                            to: rowsQuery || sqlQuery ? urls.sqlEditor({ query: rowsQuery ?? sqlQuery }) : undefined,
                            disabledReason:
                                rowsQuery || sqlQuery ? undefined : 'Select a data point to edit its underlying query.',
                            onClick: close,
                        },
                    ]}
                />
            )}
        </div>
    )
}
