import { IconCalendar } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightLogic } from 'scenes/insights/insightLogic'

import { groupsModel } from '~/models/groupsModel'
import { BreakdownFilter, NodeKind } from '~/queries/schema/schema-general'
import { DashboardMode, InsightLogicProps } from '~/types'

export function DashboardEditBar(): JSX.Element {
    const { canAutoPreview, dashboard, temporaryFilters, dashboardMode, filtersUpdated } = useValues(dashboardLogic)
    const { setDates, setProperties, setBreakdownFilter, setDashboardMode, cancelTemporary, applyTemporary } =
        useActions(dashboardLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

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
        <Popover
            visible={filtersUpdated && !canAutoPreview && dashboardMode === DashboardMode.Edit}
            className="z-1" // So that Cancel/Apply isn't above filter popovers
            overlay={
                <div className="flex items-center gap-2 m-1">
                    <LemonButton onClick={cancelTemporary} type="secondary" size="small">
                        Cancel changes
                    </LemonButton>
                    <LemonButton onClick={applyTemporary} type="primary" size="small">
                        Apply filters and preview
                    </LemonButton>
                </div>
            }
            placement="right"
            showArrow
        >
            <div
                className={clsx(
                    'flex gap-2 items-center justify-between flex-wrap border md:[&>*]:grow-0 [&>*]:grow',
                    dashboardMode === DashboardMode.Edit
                        ? '-m-1.5 p-1.5 border-border-bold border-dashed rounded-lg'
                        : 'border-transparent'
                )}
            >
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
                        ...groupsTaxonomicTypes,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.Elements,
                        TaxonomicFilterGroupType.HogQLExpression,
                    ]}
                />
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
                            if (breakdown_filter && !breakdown_filter.breakdown_type && !breakdown_filter.breakdowns) {
                                saved_breakdown_filter = null
                            }
                            setBreakdownFilter(saved_breakdown_filter)
                        }}
                        updateDisplay={() => {}}
                        size="small"
                    />
                </BindLogic>
            </div>
        </Popover>
    )
}
