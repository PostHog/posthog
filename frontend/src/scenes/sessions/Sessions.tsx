import React from 'react'
import { SessionsView } from './SessionsView'
import { hot } from 'react-hot-loader/root'
import { SavedFiltersMenu } from 'scenes/sessions/filters/SavedFiltersMenu'
import { PageHeader } from 'lib/components/PageHeader'
import { Divider } from 'antd'

export const Sessions = hot(_Sessions)
function _Sessions(): JSX.Element {
    if (true) {
        return (
            <div style={{ display: 'flex', flexDirection: 'row' }}>
                <div>
                    <PageHeader title="Sessions" />
                    <SavedFiltersMenu />
                </div>
                <Divider type="vertical" className="sessions-divider" />
                <div style={{ marginTop: 30 }}>
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
