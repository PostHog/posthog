import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { HostedSurveyRespondentHint } from 'scenes/surveys/components/HostedSurveyRespondentHint'
import { SdkVersionWarnings } from 'scenes/surveys/components/SdkVersionWarnings'
import { SurveyConditionsList } from 'scenes/surveys/components/SurveyConditions'
import { getSurveyUrl } from 'scenes/surveys/CopySurveyLink'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyDisplayConditionsSummary } from 'scenes/surveys/utils'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType, SurveyType } from '~/types'

export function LaunchSurveyButton({ children = 'Launch' }: { children?: ReactNode }): JSX.Element {
    const { survey, surveyWarnings } = useValues(surveyLogic)
    const { launchSurvey } = useActions(surveyLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const needsOptIn = !currentTeam?.surveys_opt_in
    const isHostedSurvey = survey.type === SurveyType.ExternalSurvey
    const conditionsSummary = isHostedSurvey ? [] : getSurveyDisplayConditionsSummary(survey)

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
                    LemonDialog.open({
                        title: 'Launch this survey?',
                        content: (
                            <div className="flex flex-col gap-3">
                                <SdkVersionWarnings warnings={surveyWarnings} />
                                {isHostedSurvey ? (
                                    <div className="flex flex-col gap-3 text-sm">
                                        <p className="text-secondary m-0">
                                            Once launched, anyone with the link can answer the survey. We'll copy the
                                            link to your clipboard so you can share it right away.
                                        </p>
                                        <HostedSurveyRespondentHint />
                                    </div>
                                ) : conditionsSummary.length > 0 ? (
                                    <div className="text-sm">
                                        <div className="text-secondary mb-1">
                                            This survey will be shown to users who match:
                                        </div>
                                        <SurveyConditionsList conditions={conditionsSummary} />
                                    </div>
                                ) : (
                                    <div className="text-sm text-secondary">
                                        This survey will be shown to all users.
                                    </div>
                                )}
                                {needsOptIn && (
                                    <div className="text-xs text-muted">This will enable surveys for your project.</div>
                                )}
                            </div>
                        ),
                        primaryButton: {
                            children: isHostedSurvey ? 'Launch and copy link' : 'Launch',
                            type: 'primary',
                            onClick: () => {
                                if (needsOptIn) {
                                    updateCurrentTeam({ surveys_opt_in: true })
                                }
                                if (isHostedSurvey) {
                                    void copyToClipboard(getSurveyUrl(survey.id), 'survey link')
                                }
                                launchSurvey()
                            },
                            size: 'small',
                        },
                        secondaryButton: {
                            children: 'Cancel',
                            type: 'tertiary',
                            size: 'small',
                        },
                    })
                }}
            >
                {children}
            </LemonButton>
        </AccessControlAction>
    )
}
