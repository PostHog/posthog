import ReactDOM from 'react-dom'
import React from 'react'
import { loadPostHogJS } from '~/loadPostHogJS'
import { initKea } from '~/initKea'
import { ExportedData, ExportType } from '~/exporter/types'
import { ExportViewer } from '~/exporter/ExportViewer'
import { SharedDashboard } from '~/exporter/SharedDashboard'

const exportedData: ExportedData = window.POSTHOG_EXPORTED_DATA
const { type, dashboard, organization, team } = exportedData

if (type === ExportType.Image) {
    // Disable tracking for screenshot captures
    window.JS_POSTHOG_API_KEY = null
}

loadPostHogJS()
initKea()

function Exporter(): JSX.Element {
    if (type === ExportType.Image) {
        return <ExportViewer exportedData={exportedData} />
    } else if (type === ExportType.Scene && dashboard) {
        return (
            <SharedDashboard
                dashboard={dashboard}
                availableFeatures={organization?.available_features ?? []}
                team={team ?? {}}
            />
        )
    }
    return (
        <div>
            Unknown export format: <code>{type}</code>
        </div>
    )
}

ReactDOM.render(<Exporter />, document.getElementById('root'))
