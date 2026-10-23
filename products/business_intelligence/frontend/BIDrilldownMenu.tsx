import { useActions, useValues } from 'kea'

import { IconCode, IconFilter, IconExternal } from '@posthog/icons'

import { ResultMenu, ResultMenuAction } from 'lib/components/ResultMenu/ResultMenu'
import { IconTableChart } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { BIDrilldownProps, biDrilldownLogic } from './biDrilldownLogic'

export function BIDrilldownMenu({ logicProps }: { logicProps: BIDrilldownProps }): JSX.Element | null {
    const { selection, record, queries, interaction, showRows, dashboardFilterDisabledReason } = useValues(
        biDrilldownLogic(logicProps)
    )
    const { close, viewRows, filterDashboard, openWorksheet, openSqlEditor } = useActions(biDrilldownLogic(logicProps))
    if (!selection || showRows) {
        return null
    }
    const selectedResult =
        selection.labels.map(({ name, value }) => `${name}: ${value}`).join(' · ') || 'All matching rows'
    const canFilter = !!logicProps.onFilterDashboard && !dashboardFilterDisabledReason
    const actions: ResultMenuAction[] = [
        {
            name: 'Filter dashboard by this result',
            icon: <IconFilter />,
            className: 'BIDrilldownMenu__filter',
            disabledReason: dashboardFilterDisabledReason,
            onClick: filterDashboard,
            to: record && !dashboardFilterDisabledReason ? logicProps.getDashboardFilterUrl?.(record) : undefined,
            inPlace: true,
        },
        {
            name: 'Filter in new worksheet',
            icon: <IconExternal />,
            className: 'BIDrilldownMenu__worksheet',
            disabledReason: !queries?.worksheet
                ? 'This result cannot be opened in a new worksheet. View the underlying rows instead.'
                : undefined,
            onClick: openWorksheet,
            to: queries?.worksheet
                ? `${urls.businessIntelligenceNew()}#q=${encodeURIComponent(JSON.stringify(queries.worksheet))}`
                : undefined,
        },
        {
            name: 'View underlying rows',
            icon: <IconTableChart />,
            className: 'BIDrilldownMenu__rows',
            disabledReason: !queries ? 'Check the worksheet’s data source and fields before trying again.' : undefined,
            onClick: viewRows,
            to: queries ? urls.sqlEditor({ query: queries.rows }) : undefined,
            inPlace: true,
        },
        {
            name: 'Open in SQL editor',
            icon: <IconCode />,
            className: 'BIDrilldownMenu__sql',
            disabledReason: !queries ? 'Check the worksheet’s data source and fields before trying again.' : undefined,
            onClick: openSqlEditor,
            to: queries ? urls.sqlEditor({ query: queries.rows }) : undefined,
        },
    ].filter((action) => action.className !== 'BIDrilldownMenu__filter' || canFilter)

    return (
        <ResultMenu
            selectedResult={selectedResult}
            caption={selection.previous ? 'Comparison period' : 'Current period'}
            interaction={interaction}
            actions={actions}
            canFilter={canFilter}
            close={close}
        />
    )
}
