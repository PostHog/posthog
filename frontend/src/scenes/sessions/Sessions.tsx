import React from 'react'
import { SessionsView } from './SessionsView'
import { SavedFiltersMenu } from 'scenes/sessions/filters/SavedFiltersMenu'
import { PageHeader } from 'lib/components/PageHeader'
import { Divider } from 'antd'

export function Sessions(): JSX.Element {
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
                <SessionsView key="global" />
            </div>
        </div>
    )
}
