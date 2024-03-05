import { IconCalendar } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { NotFound } from 'lib/components/NotFound'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { useEffect } from 'react'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { dashboardLogic, DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { DashboardReloadAction, LastRefreshText } from 'scenes/dashboard/DashboardReloadAction'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DashboardMode, DashboardPlacement, DashboardType } from '~/types'

import { groupsModel } from '../../models/groupsModel'
import { DashboardHeader } from './DashboardHeader'
import { EmptyDashboardComponent } from './EmptyDashboardComponent'

interface DashboardProps {
    id?: string
    dashboard?: DashboardType
    placement?: DashboardPlacement
}

export const scene: SceneExport = {
    component: DashboardScene,
    logic: dashboardLogic,
    paramsToProps: ({ params: { id, placement } }: { params: DashboardProps }): DashboardLogicProps => ({
        id: parseInt(id as string),
        placement,
    }),
}

export function Dashboard({ id, dashboard, placement }: DashboardProps = {}): JSX.Element {
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
        filters: dashboardFilters,
        dashboardMode,
        receivedErrorsFromAPI,
    } = useValues(dashboardLogic)
    const { setDashboardMode, setDates, reportDashboardViewed, setProperties, abortAnyRunningQuery } =
        useActions(dashboardLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    useEffect(() => {
        reportDashboardViewed()
        return () => {
            // request cancellation of any running queries when this component is no longer in the dom
            abortAnyRunningQuery()
        }
    }, [])

    useKeyboardHotkeys(
        placement == DashboardPlacement.Dashboard
            ? {
                  e: {
                      action: () =>
                          setDashboardMode(
                              dashboardMode === DashboardMode.Edit ? null : DashboardMode.Edit,
                              DashboardEventSource.Hotkey
                          ),
                      disabled: !canEditDashboard || (dashboardMode !== null && dashboardMode !== DashboardMode.Edit),
                  },
                  f: {
                      action: () =>
                          setDashboardMode(
                              dashboardMode === DashboardMode.Fullscreen ? null : DashboardMode.Fullscreen,
                              DashboardEventSource.Hotkey
                          ),
                      disabled: dashboardMode !== null && dashboardMode !== DashboardMode.Fullscreen,
                  },
                  escape: {
                      // Exit edit mode with Esc. Full screen mode is also exited with Esc, but this behavior is native to the browser.
                      action: () => setDashboardMode(null, DashboardEventSource.Hotkey),
                      disabled: dashboardMode !== DashboardMode.Edit,
                  },
              }
            : {},
        [setDashboardMode, dashboardMode, placement]
    )

    if (!dashboard && !itemsLoading && receivedErrorsFromAPI) {
        return <NotFound object="dashboard" />
    }

    return (
        <div className="dashboard">
            {placement == DashboardPlacement.Dashboard && <DashboardHeader />}

            {receivedErrorsFromAPI ? (
                <InsightErrorState title="There was an error loading this dashboard" />
            ) : !tiles || tiles.length === 0 ? (
                <EmptyDashboardComponent loading={itemsLoading} canEdit={canEditDashboard} />
            ) : (
                <div>
                    <div className="flex gap-2 items-center justify-between flex-wrap">
                        {![
                            DashboardPlacement.Public,
                            DashboardPlacement.Export,
                            DashboardPlacement.FeatureFlag,
                        ].includes(placement) && (
                            <div className="flex space-x-4 items-center">
                                <DateFilter
                                    showCustom
                                    dateFrom={dashboardFilters?.date_from ?? undefined}
                                    dateTo={dashboardFilters?.date_to ?? undefined}
                                    onChange={setDates}
                                    disabled={!canEditDashboard}
                                    makeLabel={(key) => (
                                        <>
                                            <IconCalendar />
                                            <span className="hide-when-small"> {key}</span>
                                        </>
                                    )}
                                />
                                <PropertyFilters
                                    onChange={setProperties}
                                    pageKey={'dashboard_' + dashboard?.id}
                                    propertyFilters={dashboard?.filters.properties}
                                    taxonomicGroupTypes={[
                                        TaxonomicFilterGroupType.EventProperties,
                                        TaxonomicFilterGroupType.PersonProperties,
                                        TaxonomicFilterGroupType.EventFeatureFlags,
                                        ...groupsTaxonomicTypes,
                                        TaxonomicFilterGroupType.Cohorts,
                                        TaxonomicFilterGroupType.Elements,
                                        TaxonomicFilterGroupType.HogQLExpression,
                                    ]}
                                />
                            </div>
                        )}
                        {placement === DashboardPlacement.FeatureFlag && dashboard?.id && (
                            <LemonButton type="secondary" size="small" to={urls.dashboard(dashboard.id)}>
                                Edit dashboard
                            </LemonButton>
                        )}
                        {placement !== DashboardPlacement.Export && (
                            <div className="flex shrink-0 space-x-4 dashoard-items-actions">
                                <div
                                    className={`left-item ${
                                        placement === DashboardPlacement.Public ? 'text-right' : ''
                                    }`}
                                >
                                    {[DashboardPlacement.Public].includes(placement) ? (
                                        <LastRefreshText />
                                    ) : (
                                        <DashboardReloadAction />
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                    <DashboardItems />
                </div>
            )}
        </div>
    )
}
