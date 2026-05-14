import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItem, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import {
    getSurveyIdsFromNotificationFilters,
    surveyNotificationsListLogic,
} from 'scenes/surveys/surveyNotificationsListLogic'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
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

function NewNotificationButton(): JSX.Element {
    const { push } = useActions(router)
    const { data } = useValues(surveysLogic)

    const eligibleSurveys = data.surveys.filter((survey: Survey) => !survey.archived)

    const items: LemonMenuItem[] = eligibleSurveys.map((survey: Survey) => ({
        key: survey.id,
        label: survey.name,
        onClick: () => push(surveyNotificationsUrl(survey.id, { notification: 'add' })),
    }))

    if (eligibleSurveys.length === 0) {
        return (
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconPlus />}
                disabledReason="Create a survey first, then set up notifications from its Notifications tab."
            >
                New notification
            </LemonButton>
        )
    }

    return (
        <LemonMenu items={[{ title: 'Add notification to…', items }]} placement="bottom-end" maxContentWidth>
            <LemonButton type="secondary" size="small" icon={<IconPlus />}>
                New notification
            </LemonButton>
        </LemonMenu>
    )
}

export function SurveyNotificationsList(): JSX.Element {
    const { notifications, notificationsLoading } = useValues(surveyNotificationsListLogic)
    const { toggleNotificationEnabled } = useActions(surveyNotificationsListLogic)
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

    if (notifications.length === 0) {
        return (
            <div className="flex flex-col items-center gap-3 rounded border border-dashed p-6 text-center">
                <div className="space-y-1">
                    <p className="m-0 text-sm font-medium">No survey notifications yet</p>
                    <p className="m-0 text-xs text-muted">
                        Send every new survey response to Slack, Discord, Microsoft Teams, or a webhook.
                    </p>
                </div>
                <NewNotificationButton />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
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
            <div>
                <NewNotificationButton />
            </div>
        </div>
    )
}
