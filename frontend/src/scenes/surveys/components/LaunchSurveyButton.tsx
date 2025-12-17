import { useActions, useValues } from 'kea'
import { ReactNode, useCallback, useMemo, useState } from 'react'

import { LemonButton, LemonDialog, lemonToast } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { dayjs } from 'lib/dayjs'
import { SdkVersionWarnings } from 'scenes/surveys/components/SdkVersionWarnings'
import { SurveyStartSchedulePicker } from 'scenes/surveys/components/SurveyStartSchedulePicker'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { SurveyFeatureWarning, getSurveyWarnings } from 'scenes/surveys/surveyVersionRequirements'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { surveysSdkLogic } from 'scenes/surveys/surveysSdkLogic'
import { doesSurveyHaveDisplayConditions } from 'scenes/surveys/utils'

import { ProductIntentContext } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, Survey, SurveyType } from '~/types'

import { NewSurvey } from '../constants'

function LaunchDialogContent({
    survey,
    surveyWarnings,
    scheduledStartTime,
    setScheduledStartTime,
}: {
    survey: Survey | NewSurvey
    surveyWarnings: SurveyFeatureWarning[]
    scheduledStartTime: string | undefined
    setScheduledStartTime: (time: string | undefined) => void
}): JSX.Element {
    return (
        <div>
            <div className="text-sm text-secondary mb-4">
                Start displaying to{' '}
                {doesSurveyHaveDisplayConditions(survey) ? 'users matching the display conditions' : 'all your users'}:
            </div>
            <SurveyStartSchedulePicker
                value={scheduledStartTime}
                onChange={setScheduledStartTime}
                manualLabel="Immediately"
                datetimeLabel="In the future"
            />
            <SdkVersionWarnings warnings={surveyWarnings} />
        </div>
    )
}

export function LaunchSurveyButton({ children = 'Launch' }: { children?: ReactNode }): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { updateSurvey } = useActions(surveyLogic)
    const { showSurveysDisabledBanner } = useValues(surveysLogic)
    const { teamSdkVersions } = useValues(surveysSdkLogic)
    const [scheduledStartTime, setScheduledStartTime] = useState<string | undefined>(
        survey.scheduled_start_datetime || undefined
    )
    const [isLaunchDialogOpen, setIsLaunchDialogOpen] = useState(false)

    const surveyWarnings = useMemo(() => {
        return typeof (survey as Survey).id === 'number' ? getSurveyWarnings(survey as Survey, teamSdkVersions) : []
    }, [survey, teamSdkVersions])

    const closeDialog = useCallback(() => {
        setIsLaunchDialogOpen(false)
    }, [])

    const updateSurveyCallback = useCallback(async () => {
        const updatedSurvey = { id: survey.id, intentContext: ProductIntentContext.SURVEY_LAUNCHED } as Partial<Survey>
        if (!scheduledStartTime) {
            updatedSurvey['start_date'] = dayjs().toISOString()
        } else {
            updatedSurvey['scheduled_start_datetime'] = scheduledStartTime
        }
        try {
            await updateSurvey(updatedSurvey)
            closeDialog()
        } catch {
            lemonToast.error('Failed to launch survey. Please try again.')
        }
    }, [closeDialog, scheduledStartTime, survey.id, updateSurvey])

    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.Survey}
                minAccessLevel={AccessControlLevel.Editor}
                userAccessLevel={survey.user_access_level}
            >
                <LemonButton
                    type="primary"
                    data-attr="launch-survey"
                    disabledReason={
                        showSurveysDisabledBanner && survey.type !== SurveyType.API
                            ? 'Please enable surveys in the banner below before launching'
                            : undefined
                    }
                    size="small"
                    onClick={() => setIsLaunchDialogOpen(true)}
                >
                    {children}
                </LemonButton>
            </AccessControlAction>

            {isLaunchDialogOpen && (
                <LemonDialog
                    title="Launch this survey?"
                    onClose={closeDialog}
                    onAfterClose={closeDialog}
                    shouldAwaitSubmit
                    content={
                        <LaunchDialogContent
                            survey={survey}
                            surveyWarnings={surveyWarnings}
                            setScheduledStartTime={setScheduledStartTime}
                            scheduledStartTime={scheduledStartTime}
                        />
                    }
                    primaryButton={{
                        children: scheduledStartTime ? `Schedule launch` : 'Launch',
                        type: 'primary',
                        onClick: updateSurveyCallback,
                        preventClosing: true,
                        size: 'small',
                    }}
                    secondaryButton={{
                        children: 'Cancel',
                        type: 'tertiary',
                        size: 'small',
                    }}
                />
            )}
        </>
    )
}
