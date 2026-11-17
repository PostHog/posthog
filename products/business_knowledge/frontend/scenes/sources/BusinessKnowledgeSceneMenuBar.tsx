import { useActions } from 'kea'

import { IconPlusSmall } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { businessKnowledgeLogic } from './businessKnowledgeLogic'

const RESOURCE_TYPE = 'business-knowledge'

export function BusinessKnowledgeSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <BusinessKnowledgeSceneMenuBarInner /> : null
}

function BusinessKnowledgeSceneMenuBarInner(): JSX.Element {
    const { openCreateModal } = useActions(businessKnowledgeLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-add-source`,
            label: 'Add source',
            icon: <IconPlusSmall />,
            opensFloatingUi: true,
            onSelect: () => openCreateModal(),
            pinned: { order: 1, variant: 'primary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
