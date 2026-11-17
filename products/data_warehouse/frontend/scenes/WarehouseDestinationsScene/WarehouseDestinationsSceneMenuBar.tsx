import { IconPlusSmall } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'warehouse-destinations'

export function WarehouseDestinationsSceneMenuBar({
    openForCreate,
}: {
    openForCreate: () => void
}): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <WarehouseDestinationsSceneMenuBarInner openForCreate={openForCreate} /> : null
}

function WarehouseDestinationsSceneMenuBarInner({ openForCreate }: { openForCreate: () => void }): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-destination`,
            label: 'New destination',
            icon: <IconPlusSmall />,
            opensFloatingUi: true,
            onSelect: openForCreate,
            pinned: { order: 1, variant: 'primary', dataAttr: 'warehouse-destinations-scene-new' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
