import './Dashboard.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { cn } from 'lib/utils/css-classes'
import { DashboardEditBar } from 'scenes/dashboard/DashboardEditBar'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { DashboardReloadAction, LastRefreshText } from 'scenes/dashboard/DashboardReloadAction'
import { DashboardLogicProps, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardPropertyFilterCombobox } from 'scenes/dashboard/DashboardPropertyFilterCombobox'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { groupsModel } from '~/models/groupsModel'
import { BreakdownFilter, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { DashboardMode, DashboardPlacement, DashboardType, DataColorThemeModel, InsightLogicProps, QueryBasedInsightModel } from '~/types'

import { teamLogic } from '../teamLogic'
import { AddInsightToDashboardModal } from './AddInsightToDashboardModal'
import { DashboardHeader } from './DashboardHeader'
import { DashboardOverridesBanner } from './DashboardOverridesBanner'
import { EmptyDashboardComponent } from './EmptyDashboardComponent'
import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'

interface DashboardProps {
    id?: string
    dashboard?: DashboardType<QueryBasedInsightModel>
    placement?: DashboardPlacement
    themes?: DataColorThemeModel[]
}

export const scene: SceneExport<DashboardLogicProps> = {
    component: DashboardScene,
    logic: dashboardLogic,
    paramsToProps: ({ params: { id, placement } }) => ({
        id: parseInt(id as string),
        placement,
    }),
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

export function Dashboard({ id, dashboard, placement, themes }: DashboardProps): JSX.Element {
    useMountedLogic(dataThemeLogic({ themes }))

    return (
        <BindLogic logic={dashboardLogic} props={{ id: parseInt(id as string), placement, dashboard }}>
            <DashboardScene />
        </BindLogic>
    )
}

function DashboardScene(): JSX.Element {
    const {
        placement,
        dashboard,
        canEditDashboard,
        tiles,
        itemsLoading,
        dashboardMode,
        dashboardFailedToLoad,
        accessDeniedToDashboard,
        hasVariables,
        effectiveEditBarFilters,
    } = useValues(dashboardLogic)
    const { setDashboardMode, setBreakdownFilter, setProperties } = useActions(dashboardLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { currentTeamId } = useValues(teamLogic)
    const { addInsightToDashboardModalVisible } = useValues(addInsightToDashboardLogic)
    const { reportDashboardViewed, abortAnyRunningQuery } = useActions(dashboardLogic)
    const hasNewTaxonomicSearch = useFeatureFlag('UX_NEW_TAXONOMIC_SEARCH')

    const insightProps: InsightLogicProps = {
        dashboardItemId: 'new',
        dashboardId: dashboard?.id,
        cachedInsight: null,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [],
            },
        },
    }

    useFileSystemLogView({
        type: 'dashboard',
        ref: dashboard?.id,
        enabled: Boolean(currentTeamId && dashboard?.id && !dashboardFailedToLoad && !accessDeniedToDashboard),
        deps: [currentTeamId, dashboard?.id, dashboardFailedToLoad, accessDeniedToDashboard],
    })

    useOnMountEffect(() => {
        reportDashboardViewed()

        // request cancellation of any running queries when this component is no longer in the dom
        return () => abortAnyRunningQuery()
    })

    if (!dashboard && !itemsLoading && !dashboardFailedToLoad) {
        return <NotFound object="dashboard" />
    }

    if (accessDeniedToDashboard) {
        return <AccessDenied object="dashboard" />
    }

    return (
        <SceneContent className={cn('dashboard')}>
            {placement == DashboardPlacement.Dashboard && <DashboardHeader />}
            {canEditDashboard && addInsightToDashboardModalVisible && <AddInsightToDashboardModal />}

            {dashboardFailedToLoad ? (
                <InsightErrorState title="There was an error loading this dashboard" />
            ) : !tiles || tiles.length === 0 ? (
                <EmptyDashboardComponent loading={itemsLoading} canEdit={canEditDashboard} />
            ) : (
                <div
                    className={cn({
                        '-mt-4': placement == DashboardPlacement.ProjectHomepage,
                    })}
                >
                    <DashboardOverridesBanner />

                    {hasNewTaxonomicSearch && (
                        <BindLogic logic={insightLogic} props={insightProps}>
                            <TaxonomicBreakdownFilter

                                insightProps={insightProps}
                                breakdownFilter={effectiveEditBarFilters.breakdown_filter}
                                isTrends={false}
                                // showLabel={false}
                                updateBreakdownFilter={(breakdown_filter) => {
                                    if (dashboardMode !== DashboardMode.Edit) {
                                        setDashboardMode(DashboardMode.Edit, null)
                                    }
                                    let saved_breakdown_filter: BreakdownFilter | null = breakdown_filter
                                    if (
                                        breakdown_filter &&
                                        !breakdown_filter.breakdown_type &&
                                        !breakdown_filter.breakdowns
                                    ) {
                                        saved_breakdown_filter = null
                                    }
                                    setBreakdownFilter(saved_breakdown_filter)
                                }}
                                updateDisplay={() => { }}
                                disablePropertyInfo
                                size="small"
                            />
                        </BindLogic>
                    )}

                    {hasNewTaxonomicSearch && (
                        <>
                            Dashboard Property Filter Combobox
                            <DashboardPropertyFilterCombobox
                                properties={effectiveEditBarFilters.properties ?? undefined}
                                onChange={(properties) => {
                                    if (dashboardMode !== DashboardMode.Edit) {
                                        setDashboardMode(DashboardMode.Edit, null)
                                    }
                                    setProperties(properties)
                                }}
                                taxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.EventProperties,
                                    TaxonomicFilterGroupType.PersonProperties,
                                    TaxonomicFilterGroupType.EventFeatureFlags,
                                    TaxonomicFilterGroupType.EventMetadata,
                                    ...groupsTaxonomicTypes,
                                    TaxonomicFilterGroupType.Cohorts,
                                    TaxonomicFilterGroupType.Elements,
                                    TaxonomicFilterGroupType.SessionProperties,
                                    TaxonomicFilterGroupType.HogQLExpression,
                                    TaxonomicFilterGroupType.DataWarehousePersonProperties,
                                ]}
                                size="small"
                            />

                            <DashboardPropertyFilterCombobox
                                properties={effectiveEditBarFilters.properties ?? undefined}
                                onChange={(properties) => {
                                    if (dashboardMode !== DashboardMode.Edit) {
                                        setDashboardMode(DashboardMode.Edit, null)
                                    }
                                    setProperties(properties)
                                }}
                                taxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.EventProperties,
                                    TaxonomicFilterGroupType.PersonProperties,
                                    TaxonomicFilterGroupType.EventFeatureFlags,
                                    TaxonomicFilterGroupType.EventMetadata,
                                    ...groupsTaxonomicTypes,
                                    TaxonomicFilterGroupType.Cohorts,
                                    TaxonomicFilterGroupType.Elements,
                                    TaxonomicFilterGroupType.SessionProperties,
                                    TaxonomicFilterGroupType.HogQLExpression,
                                    TaxonomicFilterGroupType.DataWarehousePersonProperties,
                                ]}
                                size="small"
                            />
                        </>
                    )}

                    <SceneStickyBar showBorderBottom={false}>
                        <div className="flex flex-col gap-2 justify-between">
                            {![
                                DashboardPlacement.Public,
                                DashboardPlacement.Export,
                                DashboardPlacement.FeatureFlag,
                                DashboardPlacement.Group,
                                DashboardPlacement.Builtin,
                            ].includes(placement) &&
                                dashboard && <DashboardEditBar />}
                            {[DashboardPlacement.FeatureFlag, DashboardPlacement.Group].includes(placement) &&
                                dashboard?.id && (
                                    <LemonButton type="secondary" size="small" to={urls.dashboard(dashboard.id)}>
                                        {placement === DashboardPlacement.Group
                                            ? 'Edit dashboard template'
                                            : 'Edit dashboard'}
                                    </LemonButton>
                                )}
                            {![DashboardPlacement.Export, DashboardPlacement.Builtin].includes(placement) && (
                                <div
                                    className={clsx('flex shrink-0 deprecated-space-x-4 dashoard-items-actions', {
                                        'mt-7': hasVariables,
                                    })}
                                >
                                    <div
                                        className={`left-item ${placement === DashboardPlacement.Public ? 'text-right' : ''
                                            }`}
                                    >
                                        {[DashboardPlacement.Public].includes(placement) ? (
                                            <LastRefreshText />
                                        ) : !(dashboardMode === DashboardMode.Edit) ? (
                                            <DashboardReloadAction />
                                        ) : null}
                                    </div>
                                </div>
                            )}
                        </div>
                    </SceneStickyBar>

                    <DashboardItems />
                </div>
            )}
        </SceneContent>
    )
}
