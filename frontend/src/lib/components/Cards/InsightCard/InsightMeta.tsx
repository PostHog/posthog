import { lemonToast } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { CardMeta } from 'lib/components/Cards/CardMeta'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { DashboardPrivilegeLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
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
import { isDataVisualizationNode } from '~/queries/utils'
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
        | 'refreshEnabled'
        | 'loading'
        | 'rename'
        | 'duplicate'
        | 'dashboardId'
        | 'moveToDashboard'
        | 'showEditingControls'
        | 'showDetailsControls'
        | 'moreButtons'
        | 'variablesOverride'
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
    variablesOverride,
    removeFromDashboard,
    deleteWithUndo,
    refresh,
    refreshEnabled,
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
    const { short_id, query, name, dashboards, next_allowed_client_refresh: nextAllowedClientRefresh } = insight
    const { insightProps } = useValues(insightLogic)
    const { exportContext } = useValues(insightDataLogic(insightProps))
    const { samplingFactor } = useValues(insightVizDataLogic(insightProps))
    const { nameSortedDashboards } = useValues(dashboardsModel)

    const otherDashboards = nameSortedDashboards.filter((d) => !dashboards?.includes(d.id))

    // (@zach) Access Control TODO: add access control checks for remove from dashboard
    const editable = insight.effective_privilege_level >= DashboardPrivilegeLevel.CanEdit

    const summary = useSummarizeInsight()(insight.query)
    const refreshDisabledReason =
        nextAllowedClientRefresh && dayjs(nextAllowedClientRefresh).isAfter(dayjs())
            ? 'You are viewing the most recent calculated results.'
            : loading || !refreshEnabled
            ? 'Refreshing...'
            : undefined

    return (
        <CardMeta
            ribbonColor={ribbonColor}
            showEditingControls={showEditingControls}
            showDetailsControls={showDetailsControls}
            refresh={refresh}
            refreshDisabledReason={refreshDisabledReason}
            setAreDetailsShown={setAreDetailsShown}
            areDetailsShown={areDetailsShown}
            topHeading={<TopHeading query={insight.query} lastRefresh={insight.last_refresh} />}
            content={
                <InsightMetaContent
                    link={urls.insightView(short_id, dashboardId, variablesOverride)}
                    title={name}
                    fallbackTitle={summary}
                    description={insight.description}
                    loading={loading}
                    tags={insight.tags}
                />
            }
            metaDetails={
                <InsightDetails query={insight.query} footerInfo={insight} variablesOverride={variablesOverride} />
            }
            samplingFactor={samplingFactor}
            moreButtons={
                <>
                    <>
                        <LemonButton to={urls.insightView(short_id, dashboardId, variablesOverride)} fullWidth>
                            View
                        </LemonButton>
                        {refresh && (
                            <LemonButton
                                onClick={() => {
                                    refresh()
                                }}
                                disabledReason={refreshDisabledReason}
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
                        <LemonButton
                            to={
                                isDataVisualizationNode(query)
                                    ? urls.sqlEditor(undefined, undefined, short_id)
                                    : urls.insightEdit(short_id)
                            }
                            fullWidth
                        >
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
                                <LemonButton
                                    status="danger"
                                    onClick={() => {
                                        void (async () => {
                                            try {
                                                await deleteWithUndo?.()
                                            } catch (error: any) {
                                                lemonToast.error(`Failed to delete insight meta: ${error.detail}`)
                                            }
                                        })()
                                    }}
                                    fullWidth
                                >
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

export function InsightMetaContent({
    title,
    fallbackTitle,
    description,
    link,
    loading,
    tags,
}: {
    title: string
    fallbackTitle?: string
    description?: string
    link?: string
    loading?: boolean
    tags?: string[]
}): JSX.Element {
    let titleEl: JSX.Element = (
        <h4 title={title} data-attr="insight-card-title">
            {title || <i>{fallbackTitle || 'Untitled'}</i>}
            {loading && (
                <Tooltip
                    title="This insight is queued to check for newer results. It will be updated soon."
                    placement="top-end"
                >
                    <span className="text-accent text-sm font-medium ml-1.5">
                        <Spinner className="mr-1.5 text-base" />
                        Refreshing
                    </span>
                </Tooltip>
            )}
        </h4>
    )
    if (link) {
        titleEl = <Link to={link}>{titleEl}</Link>
    }

    return (
        <>
            {titleEl}
            {!!description && (
                <LemonMarkdown className="CardMeta__description" lowKeyHeadings>
                    {description}
                </LemonMarkdown>
            )}
            {tags && tags.length > 0 && <ObjectTags tags={tags} staticOnly />}
            <LemonTableLoader loading={loading} />
        </>
    )
}
