import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { NewNotebookButton } from './NewNotebookButton'

const RESOURCE_TYPE = 'notebooks'

export function NotebooksSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    return <NotebooksSceneMenuBarInner />
}

function NotebooksSceneMenuBarInner(): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-notebook`,
            label: 'New notebook',
            icon: <IconPlus />,
            disabledReason:
                getAccessControlDisabledReason(AccessControlResourceType.Notebook, AccessControlLevel.Editor) ??
                undefined,
            onSelect: () => router.actions.push(urls.notebook('new')),
            pinned: { order: 0, variant: 'primary', dataAttr: 'new-notebook', render: () => <NewNotebookButton /> },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
