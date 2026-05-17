import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDropdown, LemonInput, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { MailHog } from 'lib/components/hedgehogs'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { ConfirmDeleteButton } from 'scenes/surveys/components/ConfirmDeleteButton'
import {
    getSurveyIdsFromNotificationFilters,
    surveyNotificationsListLogic,
} from 'scenes/surveys/surveyNotificationsListLogic'
import { urls } from 'scenes/urls'

import { HogFunctionType } from '~/types'

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

function NewNotificationButton({
    type = 'secondary',
    size = 'small',
}: {
    type?: 'primary' | 'secondary'
    size?: 'small' | 'medium'
}): JSX.Element {
    const { push } = useActions(router)
    const {
        selectableSurveys,
        filteredSelectableSurveys,
        knownSurveysLoading,
        knownSurveysFailed,
        surveyPickerSearch,
        surveyPickerVisible,
    } = useValues(surveyNotificationsListLogic)
    const { setSurveyPickerSearch, setSurveyPickerVisible } = useActions(surveyNotificationsListLogic)

    const hasSurveys = selectableSurveys.length > 0
    const disabledReason = knownSurveysLoading
        ? undefined
        : knownSurveysFailed
          ? "We couldn't load your surveys — retry from the warning above."
          : !hasSurveys
            ? 'Create a survey first before adding notifications.'
            : undefined

    const handlePick = (surveyId: string): void => {
        push(surveyNotificationsUrl(surveyId, { notification: 'add' }))
        setSurveyPickerVisible(false)
    }

    return (
        <LemonDropdown
            visible={surveyPickerVisible}
            onVisibilityChange={setSurveyPickerVisible}
            closeOnClickInside={false}
            matchWidth={false}
            placement="bottom-end"
            overlay={
                <div className="flex flex-col gap-2 w-80 max-w-full">
                    <LemonInput
                        type="search"
                        placeholder="Search surveys…"
                        value={surveyPickerSearch}
                        onChange={setSurveyPickerSearch}
                        autoFocus
                        fullWidth
                    />
                    <div className="flex flex-col gap-px max-h-80 overflow-y-auto">
                        {filteredSelectableSurveys.length === 0 ? (
                            <p className="m-0 p-2 text-xs text-muted text-center">
                                {surveyPickerSearch ? 'No surveys match your search.' : 'No surveys available.'}
                            </p>
                        ) : (
                            filteredSelectableSurveys.map((survey) => (
                                <LemonButton
                                    key={survey.id}
                                    fullWidth
                                    size="small"
                                    role="menuitem"
                                    onClick={() => handlePick(survey.id)}
                                >
                                    <span className="truncate">{survey.name}</span>
                                </LemonButton>
                            ))
                        )}
                    </div>
                </div>
            }
        >
            <LemonButton
                type={type}
                size={size}
                icon={<IconPlus />}
                loading={knownSurveysLoading}
                disabledReason={disabledReason}
                data-attr="survey-list-new-notification-button"
            >
                Add notification
            </LemonButton>
        </LemonDropdown>
    )
}

export function SurveyNotificationsList(): JSX.Element {
    const { notifications, notificationsLoading, notificationsFailed, knownSurveysFailed } =
        useValues(surveyNotificationsListLogic)
    const { toggleNotificationEnabled, deleteNotification, loadNotifications, loadKnownSurveys } =
        useActions(surveyNotificationsListLogic)
    const { push } = useActions(router)

    if (notificationsLoading) {
        return (
            <div className="flex flex-col gap-1.5">
                {Array.from({ length: 3 }).map((_, i) => (
                    <div key={i} className="flex items-center gap-2 rounded border p-2 h-12">
                        <LemonSkeleton className="h-[30px] w-[30px] rounded shrink-0" />
                        <div className="flex-1 min-w-0 flex flex-col gap-1">
                            <LemonSkeleton className="h-3 w-40 max-w-full" />
                            <LemonSkeleton className="h-2 w-28 max-w-full" />
                        </div>
                        <LemonSkeleton className="h-5 w-9 rounded-full shrink-0" />
                    </div>
                ))}
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
            <div className="flex flex-col gap-3">
                {knownSurveysFailed ? (
                    <LemonBanner
                        type="warning"
                        action={{ children: 'Retry', onClick: () => loadKnownSurveys() }}
                        data-attr="survey-notifications-known-surveys-error"
                    >
                        We couldn't load your surveys, so picking one to notify on isn't available right now.
                    </LemonBanner>
                ) : null}
                <section className="flex flex-col items-center gap-5 px-6 py-12 text-center">
                    <MailHog className="h-32 w-auto" />
                    <div className="flex flex-col gap-1.5 max-w-md">
                        <h3 className="m-0 text-base font-semibold">Get notified when responses land</h3>
                        <p className="m-0 text-sm text-muted">
                            Pipe survey responses straight into Slack, Discord, Microsoft Teams, or any webhook.
                        </p>
                    </div>
                    <NewNotificationButton type="primary" size="medium" />
                </section>
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
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="m-0 text-sm text-muted flex-1 min-w-0">
                    Send survey responses to Slack, Discord, Microsoft Teams, or webhooks.
                </p>
                <NewNotificationButton />
            </div>
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
                            />
                            <ConfirmDeleteButton
                                onDelete={() => deleteNotification(fn)}
                                data-attr="survey-notification-list-delete"
                            />
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
