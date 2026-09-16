import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { openSurveysSettingsDialog } from 'scenes/surveys/SurveySettings'
import { teamLogic } from 'scenes/teamLogic'

import { SurveyType } from '~/types'

// The launch dialogs snapshot their content, so this component reads the setting live. The
// Configure button turns surveys on in a dialog above, and the warning must clear when it does.
export function SurveysDisabledLaunchWarning({ surveyType }: { surveyType: SurveyType }): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

    // PostHog hosts and renders these surveys, so they do not depend on the project's surveys_opt_in setting.
    if (surveyType === SurveyType.ExternalSurvey || currentTeam?.surveys_opt_in) {
        return null
    }

    return (
        <LemonBanner
            type="warning"
            action={{
                type: 'secondary',
                icon: <IconGear />,
                onClick: () => openSurveysSettingsDialog(),
                children: 'Configure',
            }}
        >
            Surveys are off for this project, so your app will not show this survey automatically. Launching does not
            change the setting.
        </LemonBanner>
    )
}
