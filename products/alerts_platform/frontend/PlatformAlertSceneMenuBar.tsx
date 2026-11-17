import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPencil } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { platformAlertLogic } from './platformAlertLogic'

const RESOURCE_TYPE = 'platform-alert'

interface PlatformAlertSceneMenuBarProps {
    sourceUrl: string | null
    sourceLabel: string
}

export function PlatformAlertSceneMenuBar(props: PlatformAlertSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <PlatformAlertSceneMenuBarInner {...props} /> : null
}

function PlatformAlertSceneMenuBarInner({ sourceUrl, sourceLabel }: PlatformAlertSceneMenuBarProps): JSX.Element {
    const { canEditRuleMetadata } = useValues(platformAlertLogic)
    const { openRuleMetadataModal } = useActions(platformAlertLogic)

    const actions: SceneAction[] = [
        ...(canEditRuleMetadata
            ? ([
                  {
                      group: 'edit',
                      id: `${RESOURCE_TYPE}-menubar-edit-rule-metadata`,
                      label: 'Edit labels and annotations',
                      icon: <IconPencil />,
                      opensFloatingUi: true,
                      onSelect: openRuleMetadataModal,
                  },
              ] satisfies SceneAction[])
            : []),
        ...(sourceUrl
            ? ([
                  {
                      group: 'view',
                      id: `${RESOURCE_TYPE}-menubar-open-source`,
                      label: `Open in ${sourceLabel}`,
                      onSelect: () => router.actions.push(sourceUrl),
                      pinned: { order: 1, variant: 'secondary', dataAttr: 'platform-alert-open-source' },
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
