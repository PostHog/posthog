import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { SdkVersionWarnings } from 'scenes/surveys/components/SdkVersionWarnings'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { doesSurveyHaveDisplayConditions } from 'scenes/surveys/utils'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function LaunchSurveyButton({ children = 'Launch' }: { children?: ReactNode }): JSX.Element {
    const { survey, surveyWarnings } = useValues(surveyLogic)
    const { launchSurvey } = useActions(surveyLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const showLaunchConfirmation = (): void => {
        LemonDialog.open({
            title: 'Launch this survey?',
            content: (
                <div>
                    <div className="text-sm text-secondary">
                        The survey will immediately start displaying to{' '}
                        {doesSurveyHaveDisplayConditions(survey)
                            ? 'users matching the display conditions'
                            : 'all your users'}
                        .
                    </div>
                    <SdkVersionWarnings warnings={surveyWarnings} />
                </div>
            ),
            primaryButton: {
                children: 'Launch',
                type: 'primary',
                onClick: () => launchSurvey(),
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Survey}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={survey.user_access_level}
        >
            <LemonButton
                type="primary"
                data-attr="launch-survey"
                size="small"
                onClick={() => {
                    if (!currentTeam?.surveys_opt_in) {
                        LemonDialog.open({
                            title: 'Enable surveys?',
                            content: (
                                <p className="text-secondary">
                                    Surveys are currently disabled for this project. Would you like to enable them and
                                    launch your survey?
                                </p>
                            ),
                            primaryButton: {
                                children: 'Enable & continue',
                                type: 'primary',
                                onClick: () => {
                                    updateCurrentTeam({ surveys_opt_in: true })
                                    showLaunchConfirmation()
                                },
                            },
                            secondaryButton: {
                                children: 'Cancel',
                                type: 'tertiary',
                            },
                        })
                    } else {
                        showLaunchConfirmation()
                    }
                }}
            >
                {children}
            </LemonButton>
        </AccessControlAction>
    )
}
