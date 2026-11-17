import { router } from 'kea-router'

import { IconCursorClick, IconPencil, IconPlusSmall } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { QuillNewActionButton } from '../components/QuillNewActionButton'

const RESOURCE_TYPE = 'actions'

export function ActionsSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    return sceneMenuBarEnabled ? <ActionsSceneMenuBarInner /> : null
}

function ActionsSceneMenuBarInner(): JSX.Element {
    const disabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Action, AccessControlLevel.Editor) ?? undefined

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            type: 'submenu',
            id: `${RESOURCE_TYPE}-menubar-new-action`,
            label: 'New action',
            icon: <IconPlusSmall />,
            disabledReason,
            items: [
                {
                    id: `${RESOURCE_TYPE}-menubar-new-action-pageview`,
                    label: 'From event or pageview',
                    icon: <IconPencil />,
                    disabledReason,
                    onSelect: () => router.actions.push(urls.createAction()),
                },
                {
                    id: `${RESOURCE_TYPE}-menubar-new-action-inspect`,
                    label: 'Inspect element on site',
                    icon: <IconCursorClick />,
                    keywords: ['toolbar'],
                    onSelect: () => router.actions.push(urls.toolbarLaunch()),
                },
            ],
            pinned: { order: 1, variant: 'primary', render: () => <QuillNewActionButton /> },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
