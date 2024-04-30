import { IconCalendar } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useEffect, useState } from 'react'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { groupsModel } from '~/models/groupsModel'
import { AnyPropertyFilter } from '~/types'

type Dates = { dateFrom?: string | null; dateTo?: string | null }

export function DashboardEditBar(): JSX.Element {
    const { dashboard, canEditDashboard, filters: dashboardFilters } = useValues(dashboardLogic)
    const { setDates, setProperties, setStale } = useActions(dashboardLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const [editMode, setEditMode] = useState(false)
    const [tempDates, setTempDates] = useState<Dates>({
        dateFrom: dashboardFilters?.date_from,
        dateTo: dashboardFilters?.date_to,
    })
    const [tempProperties, setTempProperties] = useState<AnyPropertyFilter[] | undefined>(
        dashboard?.filters.properties ?? undefined
    )

    useEffect(() => {
        const hasPendingChanges =
            tempDates.dateFrom !== dashboardFilters?.date_from ||
            tempDates.dateTo !== dashboardFilters?.date_to ||
            JSON.stringify(tempProperties) !== JSON.stringify(dashboard?.filters.properties)
        setStale(hasPendingChanges)
    }, [tempDates, tempProperties])

    const handleSave: () => void = () => {
        if (!canEditDashboard) {
            return
        }
        setDates(tempDates.dateFrom ?? null, tempDates.dateTo ?? null)
        if (tempProperties) {
            setProperties(tempProperties)
        }
        setStale(false)
        setEditMode(false)
    }

    const handleCancel: () => void = () => {
        setTempDates({
            dateFrom: dashboardFilters?.date_from,
            dateTo: dashboardFilters?.date_to,
        })
        setTempProperties(dashboard?.filters.properties ?? undefined)
        setEditMode(false)
        setStale(false)
    }

    return (
        <div className="flex gap-2 items-center justify-between flex-wrap">
            <DateFilter
                showCustom
                dateFrom={tempDates.dateFrom}
                dateTo={tempDates.dateTo}
                onChange={(dateFrom, dateTo) => setTempDates({ dateFrom, dateTo })}
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
                onChange={setTempProperties}
                pageKey={'dashboard_' + dashboard?.id}
                propertyFilters={tempProperties}
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
                    <LemonButton onClick={handleCancel} type="secondary" size="small" className="ml-4">
                        Cancel
                    </LemonButton>
                    <LemonButton onClick={handleSave} type="primary" size="small">
                        Apply and save dashboard
                    </LemonButton>
                </>
            )}
        </div>
    )
}
