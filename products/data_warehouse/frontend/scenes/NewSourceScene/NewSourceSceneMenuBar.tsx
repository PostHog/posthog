import { IconX } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'new-source'

export function NewSourceSceneMenuBar({ closeWizard }: { closeWizard: () => void }): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <NewSourceSceneMenuBarInner closeWizard={closeWizard} /> : null
}

function NewSourceSceneMenuBarInner({ closeWizard }: { closeWizard: () => void }): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            id: `${RESOURCE_TYPE}-menubar-cancel`,
            label: 'Cancel',
            icon: <IconX />,
            onSelect: closeWizard,
            pinned: { order: 1, variant: 'secondary', dataAttr: 'source-form-cancel-button' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
