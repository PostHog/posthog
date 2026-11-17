import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'

import { RenderKeybind } from 'lib/components/Shortcuts/RenderKeybind'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'transformations'

interface TransformationsSceneMenuBarProps {
    /** The title's button, which also owns the "new" keyboard shortcut. */
    newButton: JSX.Element
}

export function TransformationsSceneMenuBar(props: TransformationsSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <TransformationsSceneMenuBarInner {...props} /> : null
}

function TransformationsSceneMenuBarInner({ newButton }: TransformationsSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-transformation`,
            label: 'New transformation',
            icon: <IconPlusSmall />,
            shortcut: <RenderKeybind keybind={[keyBinds.new]} minimal />,
            onSelect: () => router.actions.push(urls.dataPipelinesNew('transformation')),
            pinned: { order: 1, variant: 'primary', render: () => newButton },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
