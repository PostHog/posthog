import clsx from 'clsx'
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
import { TZLabel } from 'lib/components/TZLabel'

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
        | 'loadingQueued'
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
    loadingQueued,
    rename,
    duplicate,
    moveToDashboard,
    areDetailsShown,
    setAreDetailsShown,
    showEditingControls = true,
    showDetailsControls = true,
    moreButtons,
}: InsightMetaProps): JSX.Element {
    const { short_id, name, dashboards, next_allowed_client_refresh: nextAllowedClientRefresh } = insight
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
            : loading || loadingQueued || !refreshEnabled
            ? 'Refreshing...'
            : undefined

    return (
        <CardMeta
            ribbonColor={ribbonColor}
            showEditingControls={showEditingControls}
            showDetailsControls={showDetailsControls}
            setAreDetailsShown={setAreDetailsShown}
            areDetailsShown={areDetailsShown}
            detailsTooltip="Show insight details, such as creator, last edit, and applied filters."
            topHeading={<TopHeading query={insight.query} lastRefresh={insight.last_refresh} />}
            content={
                <InsightMetaContent
                    link={urls.insightView(short_id, dashboardId, variablesOverride)}
                    title={name}
                    fallbackTitle={summary}
                    description={insight.description}
                    loading={loading}
                    loadingQueued={loadingQueued}
                    tags={insight.tags}
                />
            }
            metaDetails={
                <InsightDetails query={insight.query} footerInfo={insight} variablesOverride={variablesOverride} />
            }
            samplingFactor={samplingFactor}
            moreButtons={
                <>
                    {/* Insight related */}
                    {editable && (
                        <>
                            <LemonButton
                                to={
                                    isDataVisualizationNode(insight.query)
                                        ? urls.sqlEditor(undefined, undefined, short_id)
                                        : urls.insightEdit(short_id)
                                }
                                fullWidth
                            >
                                Edit
                            </LemonButton>
                            <LemonButton onClick={rename} fullWidth>
                                Rename
                            </LemonButton>
                        </>
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

                    {/* Dashboard related */}
                    {editable && (
                        <>
                            <LemonDivider />
                            {updateColor && (
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
                            {moveToDashboard && otherDashboards.length > 0 && (
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

                    {/* Data related */}
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
                    <>
                        {refresh && (
                            <LemonButton
                                onClick={() => {
                                    refresh()
                                }}
                                disabledReason={refreshDisabledReason}
                                fullWidth
                            >
                                {insight.last_refresh ? (
                                    <div className="block my-1">
                                        Refresh data
                                        <p className="text-xs text-muted mt-0.5">
                                            Last computed{' '}
                                            <TZLabel
                                                time={insight.last_refresh}
                                                noStyles
                                                className="whitespace-nowrap border-dotted border-b"
                                            />
                                        </p>
                                    </div>
                                ) : (
                                    <>Refresh data</>
                                )}
                            </LemonButton>
                        )}
                    </>

                    {/* More */}
                    {moreButtons && (
                        <>
                            <LemonDivider />
                            {moreButtons}
                        </>
                    )}
                </>
            }
            moreTooltip={
                editable ? 'Rename, duplicate, export, refresh and more…' : 'Duplicate, export, refresh and more…'
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
    loadingQueued,
    tags,
}: {
    title: string
    fallbackTitle?: string
    description?: string
    link?: string
    loading?: boolean
    loadingQueued?: boolean
    tags?: string[]
}): JSX.Element {
    let titleEl: JSX.Element = (
        <h4 title={title} data-attr="insight-card-title">
            {title || <i>{fallbackTitle || 'Untitled'}</i>}
            {(loading || loadingQueued) && (
                <Tooltip
                    title={loading ? 'This insight is loading results.' : 'This insight is waiting to load results.'}
                    placement="top-end"
                >
                    <span className={clsx('text-sm font-medium ml-1.5', loading ? 'text-accent' : 'text-muted')}>
                        <Spinner className="mr-1.5 text-base" textColored />
                        {loading ? 'Loading' : 'Waiting to load'}
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
