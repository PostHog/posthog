import React from 'react'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { FilterType } from '~/types'

export function TestAccountFiltersConfig(): JSX.Element {
    const { userUpdateRequest } = useActions(userLogic)
    const { user } = useValues(userLogic)

    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
                <PropertyFilters
                    pageKey="testaccountfilters"
                    propertyFilters={user?.team?.test_account_filters}
                    onChange={(filters: FilterType[]) =>
                        userUpdateRequest({
                            team: {
                                test_account_filters: filters,
                            },
                        })
                    }
                />
            </div>
        </div>
    )
}
