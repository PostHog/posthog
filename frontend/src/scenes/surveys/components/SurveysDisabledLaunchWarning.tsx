import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { SurveyEnableToggle } from 'scenes/surveys/SurveySettings'
import { teamLogic } from 'scenes/teamLogic'

import { SurveyType } from '~/types'

// The launch dialogs snapshot their content, so this component reads the setting live. The toggle
// sits in the launch dialog itself, and the warning must clear when the user turns surveys on.
export function SurveysDisabledLaunchWarning({ surveyType }: { surveyType: SurveyType }): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

    // PostHog hosts and renders these surveys, so they do not depend on the project's surveys_opt_in setting.
    if (surveyType === SurveyType.ExternalSurvey || currentTeam?.surveys_opt_in) {
        return null
    }

    return (
        <LemonBanner type="warning">
            <div className="flex flex-col gap-2">
                <span>
                    Surveys are off for this project, so your app will not show this survey automatically. Launching
                    does not change the setting.
                </span>
                <div>
                    <SurveyEnableToggle />
                </div>
            </div>
        </LemonBanner>
    )
}
