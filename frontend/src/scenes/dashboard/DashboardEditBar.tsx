import { IconCalendar } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { groupsModel } from '~/models/groupsModel'

export function DashboardEditBar(): JSX.Element {
    const { dashboard, canEditDashboard, temporaryFilters, isEditInProgress } = useValues(dashboardLogic)
    const { setDates, setProperties } = useActions(dashboardLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const disabledReason = !canEditDashboard ? "You don't have permission to edit this dashboard" : undefined

    return (
        <div
            className={clsx(
                'flex gap-2 items-center justify-between flex-wrap border',
                isEditInProgress ? '-m-1.5 p-1.5 border-border-bold border-dashed rounded-lg' : 'border-transparent'
            )}
        >
            <DateFilter
                showCustom
                dateFrom={temporaryFilters.date_from}
                dateTo={temporaryFilters.date_to}
                onChange={setDates}
                disabledReason={disabledReason}
                makeLabel={(key) => (
                    <>
                        <IconCalendar />
                        <span className="hide-when-small"> {key}</span>
                    </>
                )}
            />
            <PropertyFilters
                disabledReason={disabledReason}
                onChange={setProperties}
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
