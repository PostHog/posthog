import { useActions, useValues } from 'kea'

import { IconNotification } from '@posthog/icons'
import { LemonTabs } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AvailableFeature } from '~/types'

import { AdvancedActivityLogFiltersPanel } from './AdvancedActivityLogFiltersPanel'
import { AdvancedActivityLogsList } from './AdvancedActivityLogsList'
import { ExportsList } from './ExportsList'
import { advancedActivityLogsLogic } from './advancedActivityLogsLogic'

export const scene: SceneExport = {
    component: AdvancedActivityLogsScene,
    logic: advancedActivityLogsLogic,
}

export function AdvancedActivityLogsScene(): JSX.Element | null {
    const { activeTab } = useValues(advancedActivityLogsLogic)
    const { setActiveTab } = useActions(advancedActivityLogsLogic)

    const tabs = [
        {
            key: 'logs',
            label: 'Logs',
            content: (
                <div className="space-y-4">
                    <AdvancedActivityLogFiltersPanel />
                    <AdvancedActivityLogsList />
                </div>
            ),
        },
        {
            key: 'exports',
            label: 'Exports',
            content: <ExportsList />,
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Activity logs"
                resourceType={{
                    type: 'team_activity',
                    forceIcon: <IconNotification />,
                }}
            />
            <PayGateMini feature={AvailableFeature.AUDIT_LOGS}>
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as 'logs' | 'exports')}
                    tabs={tabs}
                    sceneInset
                />
            </PayGateMini>
        </SceneContent>
    )
}
