import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'

import { RenderKeybind } from 'lib/components/Shortcuts/RenderKeybind'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

const RESOURCE_TYPE = 'models'

interface ModelsSceneMenuBarProps {
    /** The title's button, which also owns the "new" keyboard shortcut. */
    createViewButton: JSX.Element
}

export function ModelsSceneMenuBar(props: ModelsSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ModelsSceneMenuBarInner {...props} /> : null
}

function ModelsSceneMenuBarInner({ createViewButton }: ModelsSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-create-view`,
            label: 'Create view',
            icon: <IconPlusSmall />,
            shortcut: <RenderKeybind keybind={[keyBinds.new]} minimal />,
            disabledReason:
                getAccessControlDisabledReason(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Editor) ??
                undefined,
            onSelect: () => router.actions.push(urls.sqlEditor({ source: 'view' })),
            pinned: { order: 1, variant: 'primary', render: () => createViewButton },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
