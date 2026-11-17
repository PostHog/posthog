import { router } from 'kea-router'

import { IconToggle } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'cohorts-staff-tools'

export function CohortsStaffToolsSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    return sceneMenuBarEnabled ? <CohortsStaffToolsSceneMenuBarInner /> : null
}

function CohortsStaffToolsSceneMenuBarInner(): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-flags-staff-tools`,
            label: 'Flags staff tools',
            icon: <IconToggle />,
            onSelect: () => router.actions.push(urls.featureFlagsStaffTools()),
            pinned: { order: 1, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
