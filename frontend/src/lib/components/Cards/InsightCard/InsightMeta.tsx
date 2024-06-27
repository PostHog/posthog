// eslint-disable-next-line no-restricted-imports
import { PieChartFilled } from '@ant-design/icons'
import { useValues } from 'kea'
import { CardMeta } from 'lib/components/Cards/CardMeta'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { DashboardPrivilegeLevel } from 'lib/constants'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Splotch, SplotchColor } from 'lib/lemon-ui/Splotch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'
import { ExporterFormat, InsightColor, QueryBasedInsightModel } from '~/types'

import { InsightCardProps } from './InsightCard'
import { InsightDetails } from './InsightDetails'

interface InsightMetaProps
    extends Pick<
        InsightCardProps,
        | 'ribbonColor'
        | 'updateColor'
        | 'removeFromDashboard'
        | 'deleteWithUndo'
        | 'refresh'
        | 'loading'
        | 'rename'
        | 'duplicate'
        | 'dashboardId'
        | 'moveToDashboard'
        | 'showEditingControls'
        | 'showDetailsControls'
        | 'moreButtons'
    > {
    insight: QueryBasedInsightModel
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
    loading,
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
    const { insightProps } = useValues(insightLogic)
    const { exportContext } = useValues(insightDataLogic(insightProps))
    const { samplingFactor } = useValues(insightVizDataLogic(insightProps))
    const { nameSortedDashboards } = useValues(dashboardsModel)

    const otherDashboards = nameSortedDashboards.filter((d) => !dashboards?.includes(d.id))
    const editable = insight.effective_privilege_level >= DashboardPrivilegeLevel.CanEdit

    const summary = useSummarizeInsight()(insight.query)

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
                            {loading && (
                                <Tooltip
                                    title="This insight is queued to check for newer results. It will be updated soon."
                                    placement="top-end"
                                >
                                    <span className="text-primary text-sm font-medium">
                                        <Spinner className="mx-1" />
                                        Refreshing
                                    </span>
                                </Tooltip>
                            )}
                        </h4>
                    </Link>

                    {!!insight.description && <div className="CardMeta__description">{insight.description}</div>}
                    {insight.tags && insight.tags.length > 0 && <ObjectTags tags={insight.tags} staticOnly />}

                    {loading && <LemonTableLoader loading={true} />}
                </>
            }
            metaDetails={<InsightDetails insight={insight} />}
            samplingNotice={
                samplingFactor && samplingFactor < 1 ? (
                    <Tooltip title={`Results calculated from ${100 * samplingFactor}% of users`}>
                        <PieChartFilled className="mr-2" style={{ color: 'var(--primary-3000-hover)' }} />
                    </Tooltip>
                ) : null
            }
            moreButtons={
                <>
                    <>
                        <LemonButton to={urls.insightView(short_id)} fullWidth>
                            View
                        </LemonButton>
                        {refresh && (
                            <LemonButton
                                onClick={() => {
                                    refresh()
                                }}
                                fullWidth
                            >
                                Refresh
                            </LemonButton>
                        )}
                    </>
                    {editable && updateColor && (
                        <LemonButtonWithDropdown
                            dropdown={{
                                overlay: Object.values(InsightColor).map((availableColor) => (
                                    <LemonButton
                                        key={availableColor}
                                        active={availableColor === (ribbonColor || InsightColor.White)}
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
                            dropdown={{
                                overlay: otherDashboards.map((otherDashboard) => (
                                    <LemonButton
                                        key={otherDashboard.id}
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
                    {editable && (
                        <LemonButton to={urls.insightEdit(short_id)} fullWidth>
                            Edit
                        </LemonButton>
                    )}
                    {editable && (
                        <LemonButton onClick={rename} fullWidth>
                            Rename
                        </LemonButton>
                    )}
                    <LemonButton
                        onClick={duplicate}
                        fullWidth
                        data-attr={
                            dashboardId ? 'duplicate-insight-from-dashboard' : 'duplicate-insight-from-card-list-view'
                        }
                    >
                        Duplicate
                    </LemonButton>
                    {exportContext ? (
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
                                        export_context: exportContext,
                                    },
                                    {
                                        export_format: ExporterFormat.XLSX,
                                        export_context: exportContext,
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
                            ) : (
                                <LemonButton status="danger" onClick={() => void deleteWithUndo?.()} fullWidth>
                                    Delete insight
                                </LemonButton>
                            )}
                        </>
                    )}
                </>
            }
        />
    )
}
