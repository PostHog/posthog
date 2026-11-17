import { IconDocument } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

interface AIObservabilityDocsSceneMenuBarProps {
    dataAttrKey: string
    docsUrl: string
}

/** The action list of an AI observability scene whose only title action is its documentation link. */
export function AIObservabilityDocsSceneMenuBar(props: AIObservabilityDocsSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <AIObservabilityDocsSceneMenuBarInner {...props} /> : null
}

function AIObservabilityDocsSceneMenuBarInner({
    dataAttrKey,
    docsUrl,
}: AIObservabilityDocsSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'view',
            id: `${dataAttrKey}-menubar-documentation`,
            label: 'Documentation',
            icon: <IconDocument />,
            onSelect: () => window.open(docsUrl, '_blank', 'noopener'),
            pinned: { order: 1, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={dataAttrKey} />
}
