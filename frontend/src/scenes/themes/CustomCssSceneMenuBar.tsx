import { IconCheck, IconEye } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'custom-css'

interface CustomCssSceneMenuBarProps {
    onPreview: () => void
    onSaveAndSet: () => void
}

export function CustomCssSceneMenuBar(props: CustomCssSceneMenuBarProps): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    return <CustomCssSceneMenuBarInner {...props} />
}

function CustomCssSceneMenuBarInner({ onPreview, onSaveAndSet }: CustomCssSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-save-and-set`,
            label: 'Save and set',
            icon: <IconCheck />,
            onSelect: onSaveAndSet,
            pinned: { order: 0, variant: 'primary' },
        },
        {
            group: 'view',
            section: 'preview',
            id: `${RESOURCE_TYPE}-menubar-preview`,
            label: 'Preview',
            icon: <IconEye />,
            onSelect: onPreview,
            pinned: { order: 0, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
