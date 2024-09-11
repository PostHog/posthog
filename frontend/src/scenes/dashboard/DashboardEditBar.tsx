import { IconCalendar } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { groupsModel } from '~/models/groupsModel'
import { DashboardMode } from '~/types'

export function DashboardEditBar(): JSX.Element {
    const { dashboard, temporaryFilters, dashboardMode } = useValues(dashboardLogic)
    const { setDates, setProperties, setDashboardMode } = useActions(dashboardLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    return (
        <div className="flex gap-2 items-center justify-between flex-wrap">
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
        </div>
    )
}
