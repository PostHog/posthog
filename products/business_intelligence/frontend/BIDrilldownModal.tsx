import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'

import { BIDrilldownProps, biDrilldownLogic } from './biDrilldownLogic'
import { captureBIWorksheetAction } from './biEditorAnalytics'

export function BIDrilldownModal({
    logicProps: props,
    onNavigate,
    navigationDisabledReason,
}: {
    logicProps: BIDrilldownProps
    onNavigate?: (worksheet: BIVisualizationNode) => void
    navigationDisabledReason?: string
}): JSX.Element {
    const { selection, queries, showRows, hierarchyDrills, interaction, record, dashboardFilterDisabledReason } =
        useValues(biDrilldownLogic(props))
    const { close, viewRows, filterDashboard } = useActions(biDrilldownLogic(props))
    return (
        <LemonModal
            title="Explore this result"
            isOpen={!!selection && (!interaction || showRows)}
            onClose={close}
            width={showRows ? '90vw' : 520}
        >
            {queries ? (
                <div className="flex flex-col gap-3">
                    <p className="m-0">
                        {selection?.previous ? 'Comparison period' : 'Current period'} ·{' '}
                        {selection?.filters.length ? 'Selected dimensions' : 'All matching rows'}
                    </p>
                    {selection?.labels.length ? (
                        <ul className="m-0 pl-4">
                            {selection.labels.map((label, index) => (
                                <li key={index} className="break-words">
                                    {label.name}: {label.value}
                                </li>
                            ))}
                        </ul>
                    ) : null}
                    <div className="flex flex-wrap gap-2">
                        {!interaction && props.onFilterDashboard && (
                            <LemonButton
                                type="primary"
                                disabledReason={dashboardFilterDisabledReason}
                                to={
                                    record && !dashboardFilterDisabledReason
                                        ? props.getDashboardFilterUrl?.(record)
                                        : undefined
                                }
                                disableClientSideRouting
                                onClick={(event) => {
                                    if (
                                        event.button !== 0 ||
                                        event.metaKey ||
                                        event.ctrlKey ||
                                        event.shiftKey ||
                                        event.altKey
                                    ) {
                                        return
                                    }
                                    event.preventDefault()
                                    filterDashboard()
                                }}
                            >
                                {record && props.isDashboardFilterSelected?.(record)
                                    ? 'Remove filter'
                                    : 'Filter dashboard by this result'}
                            </LemonButton>
                        )}
                        {!interaction &&
                            hierarchyDrills.map(({ hierarchy, next, worksheet }) => (
                                <LemonButton
                                    key={hierarchy.id}
                                    type="primary"
                                    disabledReason={navigationDisabledReason}
                                    to={
                                        onNavigate
                                            ? undefined
                                            : `${urls.businessIntelligenceNew()}#q=${encodeURIComponent(JSON.stringify(worksheet))}`
                                    }
                                    onClick={() => {
                                        onNavigate?.(worksheet)
                                        close()
                                    }}
                                    tooltip={`${hierarchy.name}: ${onNavigate ? 'filters this worksheet to the selection' : 'opens a new worksheet filtered to this selection'}`}
                                >
                                    Drill to {next.name}
                                    {onNavigate ? '' : ' in new worksheet'}
                                </LemonButton>
                            ))}
                        {!interaction && (
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    if (props.query.kind === NodeKind.BIVisualizationNode) {
                                        captureBIWorksheetAction('drilldown_worksheet_opened', props.query.config)
                                    }
                                    close()
                                }}
                                to={
                                    queries.worksheet
                                        ? `${urls.businessIntelligenceNew()}#q=${encodeURIComponent(JSON.stringify(queries.worksheet))}`
                                        : undefined
                                }
                                disabledReason={
                                    !queries.worksheet
                                        ? 'Maximum filter group depth reached. View the underlying rows instead.'
                                        : undefined
                                }
                            >
                                Filter in new worksheet
                            </LemonButton>
                        )}
                        <LemonButton
                            type="secondary"
                            onClick={viewRows}
                            disabledReason={showRows ? 'Underlying rows are already open' : undefined}
                        >
                            View underlying rows
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            to={urls.sqlEditor({ query: queries.rows })}
                            onClick={() => {
                                if (props.query.kind === NodeKind.BIVisualizationNode) {
                                    captureBIWorksheetAction('drilldown_sql_opened', props.query.config)
                                }
                                close()
                            }}
                        >
                            Open in SQL editor
                        </LemonButton>
                    </div>
                    {showRows ? (
                        <>
                            <p className="m-0 text-secondary">
                                Showing up to 1,000 source rows, before aggregation or table calculations.
                            </p>
                            <Query query={queries.rows} uniqueKey={`${props.key}.underlying`} readOnly embedded />
                        </>
                    ) : null}
                </div>
            ) : (
                <LemonBanner type="warning">
                    We couldn't build a query for this result. Close this window and check the worksheet's data source
                    and fields before trying again.
                </LemonBanner>
            )}
        </LemonModal>
    )
}
