import { IconPlus } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

const RESOURCE_TYPE = 'llm-taggers'

interface AIObservabilityTagsSceneMenuBarProps {
    onCreateTagger: () => void
}

export function AIObservabilityTagsSceneMenuBar(props: AIObservabilityTagsSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <AIObservabilityTagsSceneMenuBarInner {...props} /> : null
}

function AIObservabilityTagsSceneMenuBarInner({ onCreateTagger }: AIObservabilityTagsSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-create-tagger`,
            label: 'Create tagger',
            icon: <IconPlus />,
            opensFloatingUi: true,
            disabledReason:
                getAccessControlDisabledReason(AccessControlResourceType.Tagger, AccessControlLevel.Editor) ??
                undefined,
            onSelect: onCreateTagger,
            pinned: { order: 1, variant: 'primary', dataAttr: 'create-tagger-button' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
