import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'autoresearch'

export function AutoresearchSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <AutoresearchSceneMenuBarInner /> : null
}

function AutoresearchSceneMenuBarInner(): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-model`,
            label: 'New model',
            icon: <IconPlus />,
            onSelect: () => router.actions.push(urls.autoresearchNew()),
            pinned: { order: 1, variant: 'primary', dataAttr: 'autoresearch-new-model' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
