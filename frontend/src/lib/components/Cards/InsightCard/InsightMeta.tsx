import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { ExporterFormat, InsightColor } from '~/types'
import { Splotch, SplotchColor } from 'lib/lemon-ui/Splotch'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Link } from 'lib/lemon-ui/Link'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { InsightDetails } from './InsightDetails'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { groupsModel } from '~/models/groupsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { CardMeta } from 'lib/components/Cards/CardMeta'
import { DashboardPrivilegeLevel } from 'lib/constants'
// eslint-disable-next-line no-restricted-imports
import { PieChartFilled } from '@ant-design/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { summarizeInsight } from 'scenes/insights/summarizeInsight'
import { InsightCardProps } from './InsightCard'

interface InsightMetaProps
    extends Pick<
        InsightCardProps,
        | 'insight'
        | 'ribbonColor'
        | 'updateColor'
        | 'removeFromDashboard'
        | 'deleteWithUndo'
        | 'refresh'
        | 'rename'
        | 'duplicate'
        | 'dashboardId'
        | 'moveToDashboard'
        | 'showEditingControls'
        | 'showDetailsControls'
        | 'moreButtons'
    > {
    areDetailsShown?: boolean
    setAreDetailsShown?: React.Dispatch<React.SetStateAction<boolean>>
}

export function InsightMeta({
    insight,
    ribbonColor,
    dashboardId,
    updateColor,
    removeFromDashboard,
    deleteWithUndo,
    refresh,
    rename,
    duplicate,
    moveToDashboard,
    areDetailsShown,
    setAreDetailsShown,
    showEditingControls = true,
    showDetailsControls = true,
    moreButtons,
}: InsightMetaProps): JSX.Element {
    const { short_id, name, dashboards } = insight
    const { exporterResourceParams, insightProps } = useValues(insightLogic)
    const { reportDashboardItemRefreshed } = useActions(eventUsageLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { cohortsById } = useValues(cohortsModel)
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { mathDefinitions } = useValues(mathsLogic)

    const otherDashboards = nameSortedDashboards.filter((d) => !dashboards?.includes(d.id))
    const editable = insight.effective_privilege_level >= DashboardPrivilegeLevel.CanEdit

    // not all interactions are currently implemented for queries
    const allInteractionsAllowed = !insight.query

    const summary = summarizeInsight(insight.query, insight.filters, {
        aggregationLabel,
        cohortsById,
        mathDefinitions,
    })

    return (
        <CardMeta
            ribbonColor={ribbonColor}
            showEditingControls={showEditingControls}
            showDetailsControls={showDetailsControls}
            setAreDetailsShown={setAreDetailsShown}
            areDetailsShown={areDetailsShown}
            topHeading={<TopHeading insight={insight} />}
            meta={
                <>
                    <Link to={urls.insightView(short_id)}>
                        <h4 title={name} data-attr="insight-card-title">
                            {name || <i>{summary}</i>}
                        </h4>
                    </Link>

                    {!!insight.description && <div className="CardMeta__description">{insight.description}</div>}
                    {insight.tags && insight.tags.length > 0 && <ObjectTags tags={insight.tags} staticOnly />}
                </>
            }
            metaDetails={<InsightDetails insight={insight} />}
            samplingNotice={
                insight.filters.sampling_factor && insight.filters.sampling_factor < 1 ? (
                    <Tooltip title={`Results calculated from ${100 * insight.filters.sampling_factor}% of users`}>
                        <PieChartFilled className="mr-2" style={{ color: 'var(--primary-3000-hover)' }} />
                    </Tooltip>
                ) : null
            }
            moreButtons={
                <>
                    {allInteractionsAllowed && (
                        <>
                            <LemonButton status="stealth" to={urls.insightView(short_id)} fullWidth>
                                View
                            </LemonButton>
                            {refresh && (
                                <LemonButton
                                    status="stealth"
                                    onClick={() => {
                                        refresh()
                                        reportDashboardItemRefreshed(insight)
                                    }}
                                    fullWidth
                                >
                                    Refresh
                                </LemonButton>
                            )}
                        </>
                    )}
                    {editable && updateColor && (
                        <LemonButtonWithDropdown
                            status="stealth"
                            dropdown={{
                                overlay: Object.values(InsightColor).map((availableColor) => (
                                    <LemonButton
                                        key={availableColor}
                                        active={availableColor === (ribbonColor || InsightColor.White)}
                                        status="stealth"
                                        onClick={() => updateColor(availableColor)}
                                        icon={
                                            availableColor !== InsightColor.White ? (
                                                <Splotch color={availableColor as string as SplotchColor} />
                                            ) : null
                                        }
                                        fullWidth
                                    >
                                        {availableColor !== InsightColor.White
                                            ? capitalizeFirstLetter(availableColor)
                                            : 'No color'}
                                    </LemonButton>
                                )),
                                placement: 'right-start',
                                fallbackPlacements: ['left-start'],
                                actionable: true,
                                closeParentPopoverOnClickInside: true,
                            }}
                            fullWidth
                        >
                            Set color
                        </LemonButtonWithDropdown>
                    )}
                    {editable && moveToDashboard && otherDashboards.length > 0 && (
                        <LemonButtonWithDropdown
                            status="stealth"
                            dropdown={{
                                overlay: otherDashboards.map((otherDashboard) => (
                                    <LemonButton
                                        key={otherDashboard.id}
                                        status="stealth"
                                        onClick={() => {
                                            moveToDashboard(otherDashboard)
                                        }}
                                        fullWidth
                                    >
                                        {otherDashboard.name || <i>Untitled</i>}
                                    </LemonButton>
                                )),
                                placement: 'right-start',
                                fallbackPlacements: ['left-start'],
                                actionable: true,
                                closeParentPopoverOnClickInside: true,
                            }}
                            fullWidth
                        >
                            Move to
                        </LemonButtonWithDropdown>
                    )}
                    <LemonDivider />
                    {editable && allInteractionsAllowed && (
                        <LemonButton status="stealth" to={urls.insightEdit(short_id)} fullWidth>
                            Edit
                        </LemonButton>
                    )}
                    {editable && (
                        <LemonButton status="stealth" onClick={rename} fullWidth>
                            Rename
                        </LemonButton>
                    )}
                    <LemonButton
                        status="stealth"
                        onClick={duplicate}
                        fullWidth
                        data-attr={
                            dashboardId ? 'duplicate-insight-from-dashboard' : 'duplicate-insight-from-card-list-view'
                        }
                    >
                        Duplicate
                    </LemonButton>
                    {exporterResourceParams ? (
                        <>
                            <LemonDivider />
                            <ExportButton
                                fullWidth
                                items={[
                                    {
                                        export_format: ExporterFormat.PNG,
                                        insight: insight.id,
                                        dashboard: insightProps.dashboardId,
                                    },
                                    {
                                        export_format: ExporterFormat.CSV,
                                        export_context: exporterResourceParams,
                                    },
                                ]}
                            />
                        </>
                    ) : null}
                    {moreButtons && (
                        <>
                            <LemonDivider />
                            {moreButtons}
                        </>
                    )}
                    {editable && (
                        <>
                            <LemonDivider />
                            {removeFromDashboard ? (
                                <LemonButton status="danger" onClick={removeFromDashboard} fullWidth>
                                    Remove from dashboard
                                </LemonButton>
                            ) : allInteractionsAllowed ? (
                                <LemonButton status="danger" onClick={deleteWithUndo} fullWidth>
                                    Delete insight
                                </LemonButton>
                            ) : null}
                        </>
                    )}
                </>
            }
        />
    )
}
