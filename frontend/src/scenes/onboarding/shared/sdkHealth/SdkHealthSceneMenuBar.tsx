import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconBell, IconRefresh } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { sdkHealthLogic } from './sdkHealthLogic'

const RESOURCE_TYPE = 'sdk-health'

interface SdkHealthSceneMenuBarProps {
    scanEvents: () => void
    trackAlertsClick: () => void
}

export function SdkHealthSceneMenuBar(props: SdkHealthSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <SdkHealthSceneMenuBarInner {...props} /> : null
}

function SdkHealthSceneMenuBarInner({ scanEvents, trackAlertsClick }: SdkHealthSceneMenuBarProps): JSX.Element {
    const { reportLoading } = useValues(sdkHealthLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            id: `${RESOURCE_TYPE}-menubar-scan-events`,
            label: reportLoading ? 'Scanning events' : 'Scan events',
            icon: <IconRefresh />,
            disabledReason: reportLoading ? 'Scan in progress' : undefined,
            onSelect: scanEvents,
            pinned: { order: 1, variant: 'primary' },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-alerts`,
            label: 'Alerts',
            icon: <IconBell />,
            tooltip: 'Subscribe to alerts when SDKs go outdated',
            onSelect: () => {
                trackAlertsClick()
                router.actions.push(urls.healthAlerts(['sdk_outdated']))
            },
            pinned: { order: 2, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
