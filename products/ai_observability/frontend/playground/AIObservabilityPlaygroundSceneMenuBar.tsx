import { useActions, useValues } from 'kea'

import { IconPlay, IconPlus, IconRevert } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmPlaygroundPromptsLogic } from './llmPlaygroundPromptsLogic'
import { llmPlaygroundRunLogic } from './llmPlaygroundRunLogic'
import { QuillPlaygroundRunButton } from './QuillPlaygroundRunButton'

const RESOURCE_TYPE = 'llma-playground'

export function AIObservabilityPlaygroundSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <AIObservabilityPlaygroundSceneMenuBarInner /> : null
}

function AIObservabilityPlaygroundSceneMenuBarInner(): JSX.Element {
    const { promptConfigs } = useValues(llmPlaygroundPromptsLogic)
    const { addPromptConfig, resetPlayground } = useActions(llmPlaygroundPromptsLogic)
    const { submitting, hasRunnablePrompts } = useValues(llmPlaygroundRunLogic)
    const { submitPrompt, abortRun } = useActions(llmPlaygroundRunLogic)
    const generatingReason = submitting ? 'Generating...' : undefined
    const firstPromptId = promptConfigs[0]?.id

    const actions: SceneAction[] = [
        {
            group: 'edit',
            section: 'run',
            id: `${RESOURCE_TYPE}-menubar-run`,
            label: submitting ? 'Stop' : 'Run',
            icon: <IconPlay />,
            disabledReason:
                getAccessControlDisabledReason(AccessControlResourceType.LlmPlayground, AccessControlLevel.Editor) ??
                (submitting || hasRunnablePrompts ? undefined : 'Add messages to at least one prompt'),
            onSelect: () => (submitting ? abortRun() : submitPrompt()),
            pinned: {
                order: 3,
                variant: 'primary',
                dataAttr: 'llma-playground-run-button',
                render: () => <QuillPlaygroundRunButton />,
            },
        },
        {
            group: 'edit',
            section: 'prompts',
            id: `${RESOURCE_TYPE}-menubar-add-prompt`,
            label: 'Add prompt',
            icon: <IconPlus />,
            disabledReason: generatingReason,
            onSelect: () => addPromptConfig(firstPromptId),
            pinned: { order: 2, variant: 'secondary', dataAttr: 'llma-playground-add-prompt' },
        },
        {
            group: 'edit',
            section: 'prompts',
            id: `${RESOURCE_TYPE}-menubar-reset`,
            label: 'Reset playground',
            icon: <IconRevert />,
            tooltip: 'Reset playground to default state',
            disabledReason: generatingReason,
            onSelect: resetPlayground,
            pinned: { order: 1, variant: 'icon', dataAttr: 'llma-playground-reset' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
