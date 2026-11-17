import { router } from 'kea-router'
import posthog, { DisplaySurveyType } from 'posthog-js'

import { IconMessage, IconPlus } from '@posthog/icons'

import { FeedbackSurveyButton } from 'lib/components/FeedbackSurveyButton/FeedbackSurveyButton'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

const RESOURCE_TYPE = 'llm-prompts'

interface LLMPromptsSceneMenuBarProps {
    newPromptUrl: string
    feedbackSurveyId: string
}

export function LLMPromptsSceneMenuBar(props: LLMPromptsSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <LLMPromptsSceneMenuBarInner {...props} /> : null
}

function LLMPromptsSceneMenuBarInner({ newPromptUrl, feedbackSurveyId }: LLMPromptsSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-prompt`,
            label: 'New prompt',
            icon: <IconPlus />,
            disabledReason:
                getAccessControlDisabledReason(AccessControlResourceType.LlmAnalytics, AccessControlLevel.Editor) ??
                undefined,
            onSelect: () => router.actions.push(newPromptUrl),
            pinned: { order: 2, variant: 'primary', dataAttr: 'new-prompt-button' },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-feedback`,
            label: 'Feedback',
            icon: <IconMessage />,
            opensFloatingUi: true,
            tooltip: 'Have any questions or feedback?',
            onSelect: () =>
                posthog.displaySurvey(feedbackSurveyId, {
                    displayType: DisplaySurveyType.Popover,
                    ignoreConditions: true,
                    ignoreDelay: true,
                }),
            pinned: {
                order: 1,
                variant: 'secondary',
                render: () => <FeedbackSurveyButton surveyId={feedbackSurveyId} data-attr="prompts-feedback-button" />,
            },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
