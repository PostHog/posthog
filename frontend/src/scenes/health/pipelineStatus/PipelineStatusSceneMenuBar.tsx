import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconBell, IconRefresh } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { pipelineHealthLogic } from './pipelineHealthLogic'

const RESOURCE_TYPE = 'pipeline-status'

export function PipelineStatusSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <PipelineStatusSceneMenuBarInner /> : null
}

function PipelineStatusSceneMenuBarInner(): JSX.Element {
    const { healthIssuesLoading } = useValues(pipelineHealthLogic)
    const { loadHealthIssues } = useActions(pipelineHealthLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            id: `${RESOURCE_TYPE}-menubar-refresh`,
            label: healthIssuesLoading ? 'Refreshing' : 'Refresh',
            icon: <IconRefresh />,
            disabledReason: healthIssuesLoading ? 'Refreshing' : undefined,
            onSelect: () => loadHealthIssues(),
            pinned: { order: 1, variant: 'primary' },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-alerts`,
            label: 'Alerts',
            icon: <IconBell />,
            tooltip: 'Subscribe to alerts when a pipeline fails',
            onSelect: () => {
                // pinned: analytics event and property values are wire strings
                posthog.capture('health_alerts_entry_point_clicked', { source: 'pipeline_status' })
                router.actions.push(urls.healthAlerts(['external_data_failure', 'materialized_view_failure']))
            },
            pinned: { order: 2, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
