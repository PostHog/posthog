import { deepEqual } from 'fast-equals'
import { useActions, useValues } from 'kea'
import { ReactNode, RefObject } from 'react'

import { CapturedPersonsModal } from 'lib/components/ResultMenu/personsModalCapture'
import { ResultMenu, ResultMenuAction } from 'lib/components/ResultMenu/ResultMenu'
import { ResultMenuPoint } from 'lib/components/ResultMenu/resultMenuTrigger'
import { getPersonsRecordingFilters } from 'scenes/trends/persons-modal/getPersonsRecordingFilters'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { urls } from 'scenes/urls'

import { isActorsQuery } from '~/queries/schema/node-guards'
import { DataTableNode, DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ReplayTabs } from '~/types'

import { dashboardResultFilterLogic } from '../dashboardResultFilterLogic'
import { getDashboardResultActors, getDashboardResultFilterLink } from '../dashboardResultFilters'
import { dashboardInsightResultMenuLogic } from './dashboardInsightResultMenuLogic'

function useDashboardFilterActions(
    dashboardId: number | undefined,
    tileId: number | undefined,
    actors: CapturedPersonsModal | null,
    label: string,
    close: () => void
): ResultMenuAction[] {
    const logic = dashboardResultFilterLogic({ dashboardId: dashboardId ?? 0 })
    const { selection: activeFilter } = useValues(logic)
    const { selectResult } = useActions(logic)
    if (dashboardId === undefined || tileId === undefined) {
        return []
    }
    const query = actors ? getDashboardResultActors(actors) : null
    const selection = query ? { dashboardId, tileId, label, query } : null
    const active = activeFilter?.tileId === tileId && deepEqual(activeFilter.query, query)
    return [
        {
            name: active ? 'Remove filter' : 'Filter dashboard by this result',
            className: 'ResultMenu__filter',
            to: selection ? getDashboardResultFilterLink(window.location.href, selection, active) : undefined,
            inPlace: true,
            disabledReason: selection
                ? undefined
                : 'Right-click a result that identifies people, groups, or sessions. Other breakdowns and warehouse identities cannot filter insights.',
            onClick: () => {
                if (selection) {
                    selectResult(selection)
                }
                close()
            },
        },
    ]
}

/** The open result menu. It mounts the result logic only while the menu is open, because every
 *  dashboard tile renders the menu trigger and each mounted logic slows every later dispatch. */
export function DashboardInsightResultMenuPopover({
    dashboardId,
    tileId,
    logicKey,
    triggerRef,
    position,
    selectedResult,
    caption,
    actors,
    canViewRecordings,
    sqlQuery,
    rowsQuery,
    rowsUrl,
    close,
}: {
    dashboardId?: number
    tileId?: number
    logicKey: string
    triggerRef: RefObject<HTMLDivElement>
    position: ResultMenuPoint
    selectedResult: ReactNode
    caption: string
    actors: CapturedPersonsModal | null
    canViewRecordings: boolean
    sqlQuery: DataVisualizationNode | DataTableNode | undefined
    rowsQuery: DataTableNode | undefined
    rowsUrl: string | undefined
    close: () => void
}): JSX.Element {
    const filterActions = useDashboardFilterActions(
        dashboardId,
        tileId,
        actors,
        typeof selectedResult === 'string' ? selectedResult : caption,
        close
    )
    const recordingQuery = actors?.query
    const { selectedResult: resolvedResult, resultLoading } = useValues(
        dashboardInsightResultMenuLogic({
            key: logicKey,
            query: rowsQuery && isActorsQuery(rowsQuery.source) ? rowsQuery.source : null,
        })
    )
    const sqlUrl = resolvedResult?.sql
        ? urls.sqlEditor({ query: resolvedResult.sql })
        : sqlQuery
          ? urls.sqlEditor({ query: sqlQuery })
          : undefined
    const resultUnavailableReason = resultLoading
        ? 'Loading the selected result…'
        : 'Could not load the selected result. Right-click the data point again to retry.'

    return (
        <ResultMenu
            triggerRef={triggerRef}
            selectedResult={selectedResult}
            caption={caption}
            interaction={position}
            close={close}
            actions={[
                ...filterActions,

                {
                    name: sqlQuery ? 'View underlying rows' : 'View people',
                    className: 'ResultMenu__rows',
                    to: rowsUrl,
                    inPlace: !!actors,
                    disabledReason:
                        !actors && !sqlQuery
                            ? 'Right-click a data point to view the users or groups behind it.'
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
                          : 'Right-click a data point to edit its underlying query.',
                    onClick: close,
                },
            ]}
        />
    )
}
