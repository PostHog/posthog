import { useActions, useValues } from 'kea'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { userLogic } from 'scenes/userLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { AvailableFeature } from '~/types'
import { dashboardLogic } from './dashboardLogic'

export function LemonDashboardHeader(): JSX.Element | null {
    const { dashboard } = useValues(dashboardLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { updateDashboard } = useActions(dashboardsModel)

    return (
        dashboard && (
            <PageHeader
                title={
                    <EditableField
                        name="name"
                        value={dashboard.name || ''}
                        placeholder="Name this dashboard"
                        onSave={(value) => updateDashboard({ id: dashboard.id, name: value })}
                        minLength={1}
                    />
                }
                caption={
                    hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) && (
                        <EditableField
                            multiline
                            name="description"
                            value={dashboard.description || ''}
                            placeholder="Description (optional)"
                            onSave={(value) => updateDashboard({ id: dashboard.id, description: value })}
                            className="text-muted"
                            compactButtons
                        />
                    )
                }
            />
        )
    )
}
