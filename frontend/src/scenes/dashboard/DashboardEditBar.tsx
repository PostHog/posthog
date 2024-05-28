import { IconCalendar } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { groupsModel } from '~/models/groupsModel'

export function DashboardEditBar(): JSX.Element {
    const { dashboard, canEditDashboard, temporaryFilters, stale } = useValues(dashboardLogic)
    const { setDates, setProperties, cancelTemporary, applyTemporary } = useActions(dashboardLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const isEditInProgress: boolean = canEditDashboard && stale

    return (
        <Popover
            visible={isEditInProgress}
            className="z-0" // So that Cancel/Apply isn't above filter popovers
            overlay={
                <div className="flex items-center gap-2 m-1">
                    <LemonButton onClick={cancelTemporary} type="secondary" size="small">
                        Cancel changes
                    </LemonButton>
                    <LemonButton
                        onClick={applyTemporary}
                        type="primary"
                        size="small"
                        disabledReason={!stale ? 'No changes to apply' : undefined}
                    >
                        Apply and save dashboard
                    </LemonButton>
                </div>
            }
            placement="right"
            showArrow
        >
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
                    disabled={!canEditDashboard}
                    makeLabel={(key) => (
                        <>
                            <IconCalendar />
                            <span className="hide-when-small"> {key}</span>
                        </>
                    )}
                />
                <PropertyFilters
                    disabled={!canEditDashboard}
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
        </Popover>
    )
}
