import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner, LemonButton, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import {
    getSurveyIdsFromNotificationFilters,
    surveyNotificationsListLogic,
} from 'scenes/surveys/surveyNotificationsListLogic'
import { urls } from 'scenes/urls'

import { HogFunctionType, Survey } from '~/types'

function getNotificationDescription(fn: HogFunctionType): string | null {
    const inputs = fn.inputs
    if (!inputs) {
        return null
    }
    if (inputs.url?.value) {
        try {
            return new URL(String(inputs.url.value)).hostname
        } catch {
            return String(inputs.url.value)
        }
    }
    if (inputs.channel?.value) {
        return String(inputs.channel.value)
    }
    if (inputs.email?.value) {
        return String(inputs.email.value)
    }
    return null
}

function surveyNotificationsUrl(surveyId: string, params: Record<string, string> = {}): string {
    const search = new URLSearchParams({ tab: 'notifications', ...params }).toString()
    return `${urls.survey(surveyId)}?${search}`
}

function NewNotificationPicker(): JSX.Element {
    const { push } = useActions(router)
    const { selectableSurveys, knownSurveysLoading } = useValues(surveyNotificationsListLogic)

    const options = selectableSurveys.map((survey: Pick<Survey, 'id' | 'name'>) => ({
        key: survey.id,
        label: survey.name,
    }))

    const handleChange = (newValue: string[]): void => {
        const surveyId = newValue[0]
        if (surveyId) {
            push(surveyNotificationsUrl(surveyId, { notification: 'add' }))
        }
    }

    return (
        <div className="w-80 max-w-full">
            <LemonInputSelect
                mode="single"
                placeholder="Add notification to a survey…"
                title="Add notification to…"
                options={options}
                value={null}
                onChange={handleChange}
                loading={knownSurveysLoading}
                size="small"
                emptyStateComponent={
                    <div className="p-2 text-xs text-muted">No surveys to notify on. Create a survey first.</div>
                }
                data-attr="survey-list-new-notification-picker"
            />
        </div>
    )
}

export function SurveyNotificationsList(): JSX.Element {
    const { notifications, notificationsLoading, notificationsFailed, knownSurveysFailed } =
        useValues(surveyNotificationsListLogic)
    const { toggleNotificationEnabled, loadNotifications, loadKnownSurveys } = useActions(surveyNotificationsListLogic)
    const { push } = useActions(router)

    if (notificationsLoading) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-12" />
                <LemonSkeleton className="h-12" />
                <LemonSkeleton className="h-12" />
            </div>
        )
    }

    if (notificationsFailed) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadNotifications() }}
                data-attr="survey-notifications-load-error"
            >
                We couldn't load your survey notifications. Please try again in a moment.
            </LemonBanner>
        )
    }

    if (notifications.length === 0) {
        return (
            <div className="flex flex-col items-center gap-3 rounded border border-dashed p-6 text-center">
                <div className="space-y-1">
                    <p className="m-0 text-sm font-medium">No survey notifications yet</p>
                    <p className="m-0 text-xs text-muted">
                        Send every new survey response to Slack, Discord, Microsoft Teams, or a webhook.
                    </p>
                </div>
                <NewNotificationPicker />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            {knownSurveysFailed ? (
                <LemonBanner
                    type="warning"
                    action={{ children: 'Retry', onClick: () => loadKnownSurveys() }}
                    data-attr="survey-notifications-known-surveys-error"
                >
                    We couldn't verify which surveys still exist, so notifications for deleted surveys may appear here.
                </LemonBanner>
            ) : null}
            <div className="flex flex-col gap-1.5">
                {notifications.map((fn) => {
                    const description = getNotificationDescription(fn)
                    const surveyId = getSurveyIdsFromNotificationFilters(fn.filters)[0] ?? null

                    const handleEdit = (): void => {
                        if (surveyId) {
                            push(surveyNotificationsUrl(surveyId, { notification: fn.id }))
                        }
                    }

                    return (
                        <div key={fn.id} className="flex items-center gap-2 rounded border p-2">
                            <HogFunctionIcon src={fn.icon_url} size="small" />
                            <div className="flex-1 min-w-0">
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    onClick={handleEdit}
                                    disabledReason={
                                        surveyId ? undefined : 'This notification is not linked to a survey.'
                                    }
                                    className="font-medium p-0 h-auto min-h-0"
                                    noPadding
                                >
                                    <span className="truncate">{fn.name}</span>
                                </LemonButton>
                                {description ? <div className="text-xs text-muted truncate">{description}</div> : null}
                            </div>
                            <LemonSwitch
                                checked={fn.enabled}
                                onChange={() => toggleNotificationEnabled(fn.id, !fn.enabled)}
                                size="small"
                            />
                        </div>
                    )
                })}
            </div>
            <NewNotificationPicker />
        </div>
    )
}
