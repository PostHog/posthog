import { router } from 'kea-router'

import { IconArrowLeft } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'llm-cluster'

export function AIObservabilityClusterSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <AIObservabilityClusterSceneMenuBarInner /> : null
}

function AIObservabilityClusterSceneMenuBarInner(): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-back-to-clusters`,
            label: 'Back to clusters',
            icon: <IconArrowLeft />,
            onSelect: () => router.actions.push(urls.aiObservabilityClusters()),
            pinned: { order: 1, variant: 'secondary', dataAttr: 'clusters-back-button' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
