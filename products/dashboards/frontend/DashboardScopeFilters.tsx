import { BindLogic, useActions, useValues } from 'kea'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { groupsModel } from '~/models/groupsModel'
import { BreakdownFilter, NodeKind } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { TaxonomicBreakdownFilter } from 'products/product_analytics/frontend/insights/editor/filters/BreakdownFilter/TaxonomicBreakdownFilter'

import { DashboardControlSlot } from './DashboardControlSlot'
import { DashboardIntervalFilter } from './DashboardIntervalFilter'
import { QuillDashboardPropertyFilters } from './QuillDashboardPropertyFilters'

interface DashboardScopeFiltersProps {
    showIntervalFilter: boolean
    /**
     * Keys the property and breakdown filter logics. The bar keeps its copy mounted while the "Filters" menu shows
     * a second copy, so the two copies need different keys to keep their open popovers apart.
     */
    logicKeySuffix?: string
}

/** The interval, property and breakdown filters, which change which data every insight on the dashboard reads. */
export function DashboardScopeFilters({
    showIntervalFilter,
    logicKeySuffix = '',
}: DashboardScopeFiltersProps): JSX.Element {
    const { dashboard, dashboardEditing, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setProperties, setBreakdownFilter, setDashboardEditing } = useActions(dashboardLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const quillSurface = useQuillSurface()

    const { hasPageview, hasScreen } = getProjectEventExistence()

    const insightProps: InsightLogicProps = {
        dashboardItemId: logicKeySuffix ? `new-${logicKeySuffix}` : 'new',
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
        <>
            {showIntervalFilter && (
                <DashboardControlSlot control="interval" hasValue={effectiveEditBarFilters.interval != null}>
                    <DashboardIntervalFilter />
                </DashboardControlSlot>
            )}
            <DashboardControlSlot control="properties" hasValue={(effectiveEditBarFilters.properties?.length ?? 0) > 0}>
                <PropertyFilters
                    onChange={(properties) => {
                        if (!dashboardEditing) {
                            setDashboardEditing(true, DashboardEventSource.DashboardFilters)
                        }
                        setProperties(properties)
                    }}
                    pageKey={'dashboard_' + dashboard?.id + (logicKeySuffix ? `_${logicKeySuffix}` : '')}
                    propertyFilters={effectiveEditBarFilters.properties}
                    renderControls={
                        quillSurface ? (controls) => <QuillDashboardPropertyFilters {...controls} /> : undefined
                    }
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.EventFeatureFlags,
                        TaxonomicFilterGroupType.EventMetadata,
                        ...(hasPageview ? [TaxonomicFilterGroupType.PageviewUrls] : []),
                        ...(hasScreen ? [TaxonomicFilterGroupType.Screens] : []),
                        TaxonomicFilterGroupType.EmailAddresses,
                        ...groupsTaxonomicTypes,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.Elements,
                        TaxonomicFilterGroupType.SessionProperties,
                        TaxonomicFilterGroupType.HogQLExpression,
                        TaxonomicFilterGroupType.DataWarehousePersonProperties,
                    ]}
                />
            </DashboardControlSlot>
            <DashboardControlSlot control="breakdown" hasValue={!!effectiveEditBarFilters.breakdown_filter}>
                <BindLogic logic={insightLogic} props={insightProps}>
                    <TaxonomicBreakdownFilter
                        insightProps={insightProps}
                        breakdownFilter={effectiveEditBarFilters.breakdown_filter}
                        isTrends={false}
                        isFunnels={false}
                        showLabel={false}
                        updateBreakdownFilter={(breakdown_filter) => {
                            if (!dashboardEditing) {
                                setDashboardEditing(true, DashboardEventSource.DashboardFilters)
                            }
                            const merged: BreakdownFilter = {
                                ...effectiveEditBarFilters.breakdown_filter,
                                ...breakdown_filter,
                            }
                            // taxonomicBreakdownFilterLogic can generate an empty breakdown_filter object
                            setBreakdownFilter(!merged.breakdown_type && !merged.breakdowns ? null : merged)
                        }}
                        updateDisplay={() => {}}
                        disablePropertyInfo
                        size="small"
                        hideAddWhenFull={quillSurface}
                    />
                </BindLogic>
            </DashboardControlSlot>
        </>
    )
}
