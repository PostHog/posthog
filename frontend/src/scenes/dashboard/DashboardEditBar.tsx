import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightLogic } from 'scenes/insights/insightLogic'

import { groupsModel } from '~/models/groupsModel'
import { VariablesForDashboard } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { BreakdownFilter, NodeKind } from '~/schema'
import { DashboardMode, InsightLogicProps } from '~/types'

export function DashboardEditBar(): JSX.Element {
    const {
        canAutoPreview,
        dashboard,
        loadingPreview,
        cancellingPreview,
        temporaryFilters,
        dashboardMode,
        filtersUpdated,
        dashboardVariables,
    } = useValues(dashboardLogic)
    const { setDates, setProperties, setBreakdownFilter, setDashboardMode, previewTemporaryFilters } =
        useActions(dashboardLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const hasVariables = Object.keys(dashboardVariables).length > 0

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

    return (
        // Only show preview button for large dashboards where we don't automatically preview filter changes */
        <Popover
            visible={!canAutoPreview && filtersUpdated}
            overlay={
                <div className="m-1 flex items-center gap-2">
                    <LemonButton
                        onClick={() => setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges)}
                        loading={cancellingPreview}
                        type="secondary"
                        size="small"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton onClick={previewTemporaryFilters} loading={loadingPreview} type="primary" size="small">
                        Apply filters and preview
                    </LemonButton>
                </div>
            }
            placement="bottom"
            showArrow
        >
            <div
                className={clsx(
                    'flex flex-wrap items-end gap-2 border [&>*]:grow md:[&>*]:grow-0',
                    dashboardMode === DashboardMode.Edit
                        ? 'border-primary -m-1.5 rounded-lg border-dashed p-1.5'
                        : 'border-transparent'
                )}
            >
                <div className={clsx('content-end', { 'h-[61px]': hasVariables })}>
                    <DateFilter
                        showCustom
                        dateFrom={temporaryFilters.date_from}
                        dateTo={temporaryFilters.date_to}
                        onChange={(from_date, to_date) => {
                            if (dashboardMode !== DashboardMode.Edit) {
                                setDashboardMode(DashboardMode.Edit, null)
                            }
                            setDates(from_date, to_date)
                        }}
                        makeLabel={(key) => (
                            <>
                                <IconCalendar />
                                <span className="hide-when-small"> {key}</span>
                            </>
                        )}
                    />
                </div>
                <div className={clsx('content-end', { 'h-[61px]': hasVariables })}>
                    <PropertyFilters
                        onChange={(properties) => {
                            if (dashboardMode !== DashboardMode.Edit) {
                                setDashboardMode(DashboardMode.Edit, null)
                            }
                            setProperties(properties)
                        }}
                        pageKey={'dashboard_' + dashboard?.id}
                        propertyFilters={temporaryFilters.properties}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            TaxonomicFilterGroupType.EventFeatureFlags,
                            TaxonomicFilterGroupType.EventMetadata,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.Elements,
                            TaxonomicFilterGroupType.HogQLExpression,
                        ]}
                    />
                </div>
                <div className={clsx('content-end', { 'h-[61px]': hasVariables })}>
                    <BindLogic logic={insightLogic} props={insightProps}>
                        <TaxonomicBreakdownFilter
                            insightProps={insightProps}
                            breakdownFilter={temporaryFilters.breakdown_filter}
                            isTrends={false}
                            showLabel={false}
                            updateBreakdownFilter={(breakdown_filter) => {
                                if (dashboardMode !== DashboardMode.Edit) {
                                    setDashboardMode(DashboardMode.Edit, null)
                                }
                                let saved_breakdown_filter: BreakdownFilter | null = breakdown_filter
                                // taxonomicBreakdownFilterLogic can generate an empty breakdown_filter object
                                if (
                                    breakdown_filter &&
                                    !breakdown_filter.breakdown_type &&
                                    !breakdown_filter.breakdowns
                                ) {
                                    saved_breakdown_filter = null
                                }
                                setBreakdownFilter(saved_breakdown_filter)
                            }}
                            updateDisplay={() => {}}
                            size="small"
                        />
                    </BindLogic>
                </div>

                <VariablesForDashboard />
            </div>
        </Popover>
    )
}
