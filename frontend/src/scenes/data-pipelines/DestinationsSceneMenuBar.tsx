import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'

import { RenderKeybind } from 'lib/components/Shortcuts/RenderKeybind'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'destinations'

interface DestinationsSceneMenuBarProps {
    /** The title's button, which also owns the "new" keyboard shortcut. */
    newButton: JSX.Element
}

export function DestinationsSceneMenuBar(props: DestinationsSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <DestinationsSceneMenuBarInner {...props} /> : null
}

function DestinationsSceneMenuBarInner({ newButton }: DestinationsSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-destination`,
            label: 'New destination',
            icon: <IconPlusSmall />,
            shortcut: <RenderKeybind keybind={[keyBinds.new]} minimal />,
            onSelect: () => router.actions.push(urls.dataPipelinesNew('destination')),
            pinned: { order: 1, variant: 'primary', render: () => newButton },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
