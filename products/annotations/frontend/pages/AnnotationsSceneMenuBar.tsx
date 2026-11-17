import { useActions } from 'kea'

import { IconPlusSmall } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { NewAnnotationButton } from '../components/NewAnnotationButton'
import { annotationModalLogic } from '../logics/annotationModalLogic'

const RESOURCE_TYPE = 'annotations'

export function AnnotationsSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    return sceneMenuBarEnabled ? <AnnotationsSceneMenuBarInner /> : null
}

function AnnotationsSceneMenuBarInner(): JSX.Element {
    const { openModalToCreateAnnotation } = useActions(annotationModalLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-annotation`,
            label: 'New annotation',
            icon: <IconPlusSmall />,
            opensFloatingUi: true,
            onSelect: () => openModalToCreateAnnotation(),
            pinned: { order: 1, variant: 'primary', render: () => <NewAnnotationButton /> },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
