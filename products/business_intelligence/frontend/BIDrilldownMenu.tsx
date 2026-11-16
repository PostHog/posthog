import { useActions, useValues } from 'kea'
import { RefObject } from 'react'

import { ResultMenu, ResultMenuAction } from 'lib/components/ResultMenu/ResultMenu'
import { urls } from 'scenes/urls'

import { BIDrilldownProps, biDrilldownLogic } from './biDrilldownLogic'

export function BIDrilldownMenu({
    logicProps,
    triggerRef,
}: {
    logicProps: BIDrilldownProps
    triggerRef?: RefObject<HTMLDivElement>
}): JSX.Element | null {
    const { selection, queries, interaction, showRows, record, dashboardFilterDisabledReason } = useValues(
        biDrilldownLogic(logicProps)
    )
    const { close, viewRows, openSqlEditor, filterDashboard } = useActions(biDrilldownLogic(logicProps))
    if (!selection || !interaction || showRows) {
        return null
    }
    const selectedResult =
        selection.labels.map(({ name, value }) => `${name}: ${value}`).join(' · ') || 'All matching rows'
    const actions: ResultMenuAction[] = [
        {
            name: 'View underlying rows',
            className: 'ResultMenu__rows',
            disabledReason: !queries ? 'Check the worksheet’s data source and fields before trying again.' : undefined,
            onClick: viewRows,
            to: queries ? urls.sqlEditor({ query: queries.rows }) : undefined,
            inPlace: true,
        },
        {
            name: 'Open in SQL editor',
            className: 'ResultMenu__sql',
            disabledReason: !queries ? 'Check the worksheet’s data source and fields before trying again.' : undefined,
            onClick: openSqlEditor,
            to: queries ? urls.sqlEditor({ query: queries.rows }) : undefined,
        },
    ]

    if (logicProps.onFilterDashboard) {
        actions.push({
            name:
                record && logicProps.isDashboardFilterSelected?.(record)
                    ? 'Remove filter'
                    : 'Filter dashboard by this result',
            className: 'ResultMenu__filter',
            disabledReason: dashboardFilterDisabledReason,
            onClick: filterDashboard,
            to: record && !dashboardFilterDisabledReason ? logicProps.getDashboardFilterUrl?.(record) : undefined,
            inPlace: true,
        })
    }

    return (
        <ResultMenu
            triggerRef={triggerRef}
            selectedResult={selectedResult}
            caption={selection.previous ? 'Comparison period' : 'Current period'}
            interaction={interaction}
            actions={actions}
            close={close}
        />
    )
}
