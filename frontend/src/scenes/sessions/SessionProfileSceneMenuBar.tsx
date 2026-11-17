import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { sessionProfileLogic } from './sessionProfileLogic'

const RESOURCE_TYPE = 'session-profile'

export function SessionProfileSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    return sceneMenuBarEnabled ? <SessionProfileSceneMenuBarInner /> : null
}

function SessionProfileSceneMenuBarInner(): JSX.Element {
    const { sessionDataLoading, sessionEventsLoading } = useValues(sessionProfileLogic)
    const { loadSessionData } = useActions(sessionProfileLogic)
    const loading = sessionDataLoading || sessionEventsLoading

    const actions: SceneAction[] = [
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-refresh`,
            label: 'Refresh',
            icon: <IconRefresh />,
            disabledReason: loading ? 'Loading the session' : undefined,
            onSelect: () => loadSessionData(),
            pinned: {
                order: 1,
                variant: 'secondary',
                render: () => (
                    <Button variant="outline" onClick={() => loadSessionData()} loading={loading}>
                        <IconRefresh />
                        Refresh
                    </Button>
                ),
            },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
