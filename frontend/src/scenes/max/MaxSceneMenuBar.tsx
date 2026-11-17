import { IconOpenSidebar, IconShare } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'chat'

interface MaxSceneMenuBarProps {
    canCopyLink: boolean
    canOpenInContextPanel: boolean
    copyChatLink: () => void
    openInContextPanel: () => void
}

export function MaxSceneMenuBar(props: MaxSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <MaxSceneMenuBarInner {...props} /> : null
}

function MaxSceneMenuBarInner({
    canCopyLink,
    canOpenInContextPanel,
    copyChatLink,
    openInContextPanel,
}: MaxSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        ...(canCopyLink
            ? ([
                  {
                      group: 'file',
                      section: 'share',
                      id: `${RESOURCE_TYPE}-menubar-copy-link`,
                      label: 'Copy link to chat',
                      icon: <IconShare />,
                      onSelect: copyChatLink,
                      pinned: { order: 1, variant: 'secondary' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canOpenInContextPanel
            ? ([
                  {
                      group: 'view',
                      id: `${RESOURCE_TYPE}-menubar-open-in-context-panel`,
                      label: 'Open in context panel',
                      icon: <IconOpenSidebar />,
                      onSelect: openInContextPanel,
                      pinned: { order: 2, variant: 'secondary' },
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
