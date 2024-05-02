import { IconCalendar } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { groupsModel } from '~/models/groupsModel'

export function DashboardEditBar(): JSX.Element {
    const { dashboard, canEditDashboard, editMode, temporaryFilters, stale } = useValues(dashboardLogic)
    const { setDates, setProperties, cancelTemporary, applyTemporary, setEditMode } = useActions(dashboardLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    return (
        <div className="flex gap-2 items-center justify-between flex-wrap">
            <DateFilter
                showCustom
                dateFrom={temporaryFilters.date_from}
                dateTo={temporaryFilters.date_to}
                onChange={setDates}
                disabled={!canEditDashboard || !editMode}
                makeLabel={(key) => (
                    <>
                        <IconCalendar />
                        <span className="hide-when-small"> {key}</span>
                    </>
                )}
            />
            <PropertyFilters
                disabled={!canEditDashboard || !editMode}
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
            {canEditDashboard && !editMode ? (
                <LemonButton type="secondary" size="small" onClick={() => setEditMode(true)}>
                    Edit filters
                </LemonButton>
            ) : (
                <>
                    <LemonButton onClick={cancelTemporary} type="secondary" size="small" className="ml-4">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={applyTemporary}
                        type="primary"
                        size="small"
                        disabledReason={!stale ? 'No changes to apply' : undefined}
                    >
                        Apply and save dashboard
                    </LemonButton>
                </>
            )}
        </div>
    )
}
