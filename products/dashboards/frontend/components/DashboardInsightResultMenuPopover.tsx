import { useValues } from 'kea'
import { ReactNode, RefObject } from 'react'

import { CapturedPersonsModal } from 'lib/components/ResultMenu/personsModalCapture'
import { ResultMenu } from 'lib/components/ResultMenu/ResultMenu'
import { ResultMenuPoint } from 'lib/components/ResultMenu/resultMenuTrigger'
import { getPersonsRecordingFilters } from 'scenes/trends/persons-modal/getPersonsRecordingFilters'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { urls } from 'scenes/urls'

import { DataTableNode, DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { isActorsQuery } from '~/queries/utils'
import { ReplayTabs } from '~/types'

import { dashboardInsightResultMenuLogic } from './dashboardInsightResultMenuLogic'

/** The open result menu. It mounts the result logic only while the menu is open, because every
 *  dashboard tile renders the menu trigger and each mounted logic slows every later dispatch. */
export function DashboardInsightResultMenuPopover({
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
