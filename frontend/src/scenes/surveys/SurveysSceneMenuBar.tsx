import { router } from 'kea-router'

import { IconMessage, IconPlusSmall } from '@posthog/icons'

import { RenderKeybind } from 'lib/components/Shortcuts/RenderKeybind'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { SurveyFeedbackButton } from 'scenes/surveys/components/SurveyFeedbackButton'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { NewSurveyButton, useTrackAddNewSurvey } from './NewSurveyButton'

const RESOURCE_TYPE = 'surveys'
// pinned: the feedback survey's selector targets this element id
const FEEDBACK_BUTTON_ID = 'surveys-page-feedback-button'

export function SurveysSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <SurveysSceneMenuBarInner /> : null
}

function SurveysSceneMenuBarInner(): JSX.Element {
    const trackAddNewClick = useTrackAddNewSurvey()

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-survey`,
            label: 'New survey',
            icon: <IconPlusSmall />,
            disabledReason:
                getAccessControlDisabledReason(AccessControlResourceType.Survey, AccessControlLevel.Editor) ??
                undefined,
            shortcut: <RenderKeybind keybind={[keyBinds.new]} minimal />,
            onSelect: () => {
                trackAddNewClick()
                router.actions.push(urls.surveyWizard())
            },
            pinned: { order: 1, variant: 'primary', render: () => <NewSurveyButton /> },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-feedback`,
            label: 'Feedback',
            icon: <IconMessage />,
            opensFloatingUi: true,
            tooltip: 'Have any questions or feedback?',
            // The feedback survey opens on a click of the title button, so the row forwards its click there.
            onSelect: () => document.getElementById(FEEDBACK_BUTTON_ID)?.click(),
            pinned: { order: 1, variant: 'secondary', render: () => <SurveyFeedbackButton /> },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
