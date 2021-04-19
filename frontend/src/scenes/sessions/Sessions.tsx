import React from 'react'
import { SessionsView } from './SessionsView'
import { SavedFiltersMenu } from 'scenes/sessions/filters/SavedFiltersMenu'
import { PageHeader } from 'lib/components/PageHeader'
import { Divider } from 'antd'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export function Sessions(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    if (featureFlags['filter_by_session_props']) {
        return (
            <div className="sessions-wrapper">
                <div className="sessions-sidebar">
                    <div>
                        <PageHeader title="Sessions" />
                        <SavedFiltersMenu />
                    </div>
                    <Divider type="vertical" className="sessions-divider" />
                </div>
                <div className="sessions-with-filters">
                    <SessionsView />
                </div>
            </div>
        )
    } else {
        return (
            <>
                <PageHeader title="Sessions" />
                <SessionsView />
            </>
        )
    }
}
