import React from 'react'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { FilterType } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export function TestAccountFiltersConfig(): JSX.Element {
    const { userUpdateRequest } = useActions(userLogic)
    const { reportTestAccountFiltersUpdated } = useActions(eventUsageLogic)
    const { user } = useValues(userLogic)

    const handleChange = (filters: FilterType[]): void => {
        userUpdateRequest({
            team: {
                test_account_filters: filters,
            },
        })
        reportTestAccountFiltersUpdated(filters)
    }

    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
                <PropertyFilters
                    pageKey="testaccountfilters"
                    propertyFilters={user?.team?.test_account_filters}
                    onChange={handleChange}
                />
            </div>
        </div>
    )
}
