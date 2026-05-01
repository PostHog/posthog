import { useActions, useValues } from 'kea'

import { IconBell } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { NEW_SURVEY } from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { surveyNotificationModalLogic } from 'scenes/surveys/surveyNotificationModalLogic'

export function SurveyNotificationsCallout({ surveyId }: { surveyId: string }): JSX.Element | null {
    const logic = surveyLogic({ id: surveyId })
    const notificationModalLogic = surveyNotificationModalLogic({ surveyId })
    const { survey, surveyNotifications, surveyNotificationsLoading } = useValues(logic)
    const { openDialog } = useActions(notificationModalLogic)

    const shouldShow =
        survey.id !== NEW_SURVEY.id &&
        !!survey.start_date &&
        !survey.end_date &&
        !surveyNotificationsLoading &&
        surveyNotifications.length === 0

    if (!shouldShow) {
        return null
    }

    return (
        <LemonBanner type="info" dismissKey={`survey-notifications-callout-${surveyId}`}>
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div className="space-y-1">
                    <div className="text-sm font-medium">Stay on top of incoming survey responses</div>
                    <div className="text-sm text-muted">
                        Send every new reply to Slack, Discord, Microsoft Teams, or a webhook, and customize the
                        survey-specific message without leaving this page.
                    </div>
                </div>
                <LemonButton type="primary" size="small" icon={<IconBell />} onClick={openDialog}>
                    Set up notifications
                </LemonButton>
            </div>
        </LemonBanner>
    )
}
