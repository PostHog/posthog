import { useActions, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AdvancedActivityLogFiltersPanel } from './AdvancedActivityLogFiltersPanel'
import { AdvancedActivityLogsList } from './AdvancedActivityLogsList'
import { ExportsList } from './ExportsList'
import { advancedActivityLogsLogic } from './advancedActivityLogsLogic'

export const scene: SceneExport = {
    component: AdvancedActivityLogsScene,
    logic: advancedActivityLogsLogic,
}

export function AdvancedActivityLogsScene(): JSX.Element | null {
    const { isFeatureFlagEnabled, exports, activeTab } = useValues(advancedActivityLogsLogic)
    const { setActiveTab } = useActions(advancedActivityLogsLogic)

    if (!isFeatureFlagEnabled) {
        window.location.href = urls.projectHomepage()
        return null
    }

    const hasExports = exports && exports.length > 0

    const tabs = [
        {
            key: 'logs',
            label: 'Activity logs',
            content: (
                <div className="space-y-4">
                    <AdvancedActivityLogFiltersPanel />
                    <AdvancedActivityLogsList />
                </div>
            ),
        },
        ...(hasExports
            ? [
                  {
                      key: 'exports',
                      label: 'Exports',
                      content: <ExportsList />,
                  },
              ]
            : []),
    ]

    return (
        <div>
            <PageHeader caption="Track all changes and activities in your organization" />
            <LemonTabs activeKey={activeTab} onChange={(key) => setActiveTab(key as 'logs' | 'exports')} tabs={tabs} />
        </div>
    )
}
