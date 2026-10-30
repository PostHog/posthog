import { LemonDialog } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { HostedSurveyRespondentHint } from 'scenes/surveys/components/HostedSurveyRespondentHint'
import { SdkVersionWarnings } from 'scenes/surveys/components/SdkVersionWarnings'
import { SurveyConditionsList } from 'scenes/surveys/components/SurveyConditions'
import { SurveysDisabledLaunchWarning } from 'scenes/surveys/components/SurveysDisabledLaunchWarning'
import { NewSurvey } from 'scenes/surveys/constants'
import { getSurveyUrl } from 'scenes/surveys/CopySurveyLink'
import { SurveyFeatureWarning } from 'scenes/surveys/surveyVersionRequirements'
import { getSurveyDisplayConditionsSummary } from 'scenes/surveys/utils'

import { Survey, SurveyType } from '~/types'

export function openLaunchSurveyDialog({
    survey,
    surveyWarnings,
    launchSurvey,
}: {
    survey: Survey | NewSurvey
    surveyWarnings: SurveyFeatureWarning[]
    launchSurvey: () => void
}): void {
    const isHostedSurvey = survey.type === SurveyType.ExternalSurvey
    const conditionsSummary = isHostedSurvey ? [] : getSurveyDisplayConditionsSummary(survey)

    LemonDialog.open({
        title: 'Launch this survey?',
        content: (
            <div className="flex flex-col gap-3">
                <SdkVersionWarnings warnings={surveyWarnings} />
                {isHostedSurvey ? (
                    <div className="flex flex-col gap-3 text-sm">
                        <p className="text-secondary m-0">
                            Once launched, anyone with the link can answer the survey. We'll copy the link to your
                            clipboard so you can share it right away.
                        </p>
                        <HostedSurveyRespondentHint />
                    </div>
                ) : conditionsSummary.length > 0 ? (
                    <div className="text-sm">
                        <div className="text-secondary mb-1">This survey will be shown to users who match:</div>
                        <SurveyConditionsList conditions={conditionsSummary} />
                    </div>
                ) : (
                    <div className="text-sm text-secondary">This survey will be shown to all users.</div>
                )}
                <SurveysDisabledLaunchWarning surveyType={survey.type} />
            </div>
        ),
        primaryButton: {
            children: isHostedSurvey ? 'Launch and copy link' : 'Launch',
            type: 'primary',
            onClick: () => {
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
}
