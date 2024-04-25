import { IconCalendar } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useEffect, useState } from 'react'

import { AnyPropertyFilter, DashboardType, FilterType } from '~/types'

type Dates = { dateFrom?: string | null; dateTo?: string | null }

interface DashboardEditBarProps {
    dashboard: DashboardType
    dashboardFilters: FilterType
    canEditDashboard: boolean
    setDates: (dateFrom: string | null, dateTo: string | null) => void
    setProperties: (properties: AnyPropertyFilter[]) => void
    groupsTaxonomicTypes: TaxonomicFilterGroupType[]
    onPendingChanges?: (stale: boolean) => void
}

export function DashboardEditBar({
    dashboard,
    dashboardFilters,
    canEditDashboard,
    setDates,
    setProperties,
    groupsTaxonomicTypes,
    onPendingChanges,
}: DashboardEditBarProps): JSX.Element {
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
        if (onPendingChanges) {
            onPendingChanges(hasPendingChanges)
        }
    }, [tempDates, tempProperties])

    const handleSave: () => void = () => {
        if (!canEditDashboard) {
            return
        }
        setDates(tempDates.dateFrom ?? null, tempDates.dateTo ?? null)
        if (tempProperties) {
            setProperties(tempProperties)
        }
        if (onPendingChanges) {
            onPendingChanges(false)
        }
        setEditMode(false)
    }

    const handleCancel: () => void = () => {
        setTempDates({
            dateFrom: dashboardFilters?.date_from,
            dateTo: dashboardFilters?.date_to,
        })
        setTempProperties(dashboard?.filters.properties ?? undefined)
        setEditMode(false)
        if (onPendingChanges) {
            onPendingChanges(false)
        }
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
