import { useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'

import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AdvancedActivityLogFiltersPanel } from './AdvancedActivityLogFiltersPanel'
import { AdvancedActivityLogsList } from './AdvancedActivityLogsList'
import { advancedActivityLogsLogic } from './advancedActivityLogsLogic'

export const scene: SceneExport = {
    component: AdvancedActivityLogsScene,
    logic: advancedActivityLogsLogic,
}

export function AdvancedActivityLogsScene(): JSX.Element | null {
    const { isFeatureFlagEnabled } = useValues(advancedActivityLogsLogic)

    if (!isFeatureFlagEnabled) {
        window.location.href = urls.projectHomepage()
        return null
    }

    return (
        <div>
            <PageHeader caption="Track all changes and activities in your organization" />
            <div className="space-y-4">
                <AdvancedActivityLogFiltersPanel />
                <LemonDivider />
                <AdvancedActivityLogsList />
            </div>
        </div>
    )
}
