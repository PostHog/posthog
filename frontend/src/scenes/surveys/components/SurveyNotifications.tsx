import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { NEW_SURVEY } from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { surveyNotificationModalLogic } from 'scenes/surveys/surveyNotificationModalLogic'
import { urls } from 'scenes/urls'

import { HogFunctionType } from '~/types'

interface SurveyNotificationsProps {
    surveyId: string
    description?: string
    buttonFullWidth?: boolean
}

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

export function SurveyNotifications({
    surveyId,
    description,
    buttonFullWidth = false,
}: SurveyNotificationsProps): JSX.Element {
    const logic = surveyLogic({ id: surveyId })
    const notificationModalLogic = surveyNotificationModalLogic({ surveyId })
    const { survey, surveyNotifications, surveyNotificationsLoading } = useValues(logic)
    const { toggleSurveyNotificationEnabled } = useActions(logic)
    const { openDialog } = useActions(notificationModalLogic)

    const isUnsavedSurvey = survey.id === NEW_SURVEY.id

    return (
        <div className="flex flex-col gap-3">
            {description ? <p className="m-0 text-sm text-muted">{description}</p> : null}
            {surveyNotificationsLoading ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-12" />
                    <LemonSkeleton className="h-12" />
                </div>
            ) : surveyNotifications.length > 0 ? (
                <div className="flex flex-col gap-1.5">
                    {surveyNotifications.map((fn) => {
                        const notificationDescription = getNotificationDescription(fn)
                        return (
                            <div key={fn.id} className="flex items-center gap-2 rounded border p-2">
                                <HogFunctionIcon src={fn.icon_url} size="small" />
                                <div className="flex-1 min-w-0">
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        to={urls.hogFunction(fn.id)}
                                        className="font-medium p-0 h-auto min-h-0"
                                        noPadding
                                    >
                                        <span className="truncate">{fn.name}</span>
                                    </LemonButton>
                                    {notificationDescription ? (
                                        <div className="text-xs text-muted truncate">{notificationDescription}</div>
                                    ) : null}
                                </div>
                                <LemonSwitch
                                    checked={fn.enabled}
                                    onChange={() => toggleSurveyNotificationEnabled(fn.id, !fn.enabled)}
                                    size="small"
                                />
                            </div>
                        )
                    })}
                </div>
            ) : (
                <p className="text-xs text-muted m-0">No notifications configured yet.</p>
            )}
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconPlus />}
                onClick={openDialog}
                fullWidth={buttonFullWidth}
                data-attr="survey-new-notification"
                disabledReason={isUnsavedSurvey ? 'Save the survey before adding notifications.' : undefined}
            >
                Add notification
            </LemonButton>
        </div>
    )
}
