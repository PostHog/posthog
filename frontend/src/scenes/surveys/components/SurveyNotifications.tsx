import { useActions, useValues } from 'kea'

import { IconCopy, IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { MailHog } from 'lib/components/hedgehogs'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { ConfirmDeleteButton } from 'scenes/surveys/components/ConfirmDeleteButton'
import { NEW_SURVEY } from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { surveyNotificationModalLogic } from 'scenes/surveys/surveyNotificationModalLogic'

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
    const {
        survey,
        surveyNotifications,
        surveyNotificationsLoading,
        reusableSurveyNotifications,
        reusableSurveyNotificationsLoading,
    } = useValues(logic)
    const { toggleSurveyNotificationEnabled, deleteSurveyNotification } = useActions(logic)
    const { openDialog } = useActions(notificationModalLogic)

    const isUnsavedSurvey = survey.id === NEW_SURVEY.id
    const addDisabledReason = isUnsavedSurvey ? 'Save the survey before adding notifications.' : undefined
    const copyDisabledReason = isUnsavedSurvey ? 'Save the survey before copying notifications.' : undefined

    const copyMenuItems: LemonMenuItems = [
        {
            title: 'Copy from existing',
            items: reusableSurveyNotifications.map((fn) => {
                const notificationDescription = getNotificationDescription(fn)
                return {
                    key: fn.id,
                    icon: <HogFunctionIcon src={fn.icon_url} size="small" />,
                    label: (
                        <div className="min-w-0">
                            <div className="truncate">{fn.name}</div>
                            {notificationDescription ? (
                                <div className="text-xs text-muted truncate">{notificationDescription}</div>
                            ) : null}
                        </div>
                    ),
                    onClick: () => openDialog({ notification: fn, intent: 'copy' }),
                }
            }),
        },
    ]

    const hasReusable = reusableSurveyNotifications.length > 0
    const showCopyControl = reusableSurveyNotificationsLoading || hasReusable

    const renderCopyControl = (buttonType: 'primary' | 'secondary'): JSX.Element | null => {
        if (!showCopyControl) {
            return null
        }
        if (reusableSurveyNotificationsLoading) {
            return (
                <LemonButton
                    type={buttonType}
                    size="small"
                    icon={<IconCopy />}
                    fullWidth={buttonFullWidth}
                    loading
                    disabledReason={copyDisabledReason}
                    data-attr="survey-copy-notification"
                >
                    Copy from existing
                </LemonButton>
            )
        }
        return (
            <LemonMenu items={copyMenuItems} placement="bottom-start" maxContentWidth>
                <LemonButton
                    type={buttonType}
                    size="small"
                    icon={<IconCopy />}
                    fullWidth={buttonFullWidth}
                    disabledReason={copyDisabledReason}
                    data-attr="survey-copy-notification"
                >
                    Copy from existing
                </LemonButton>
            </LemonMenu>
        )
    }

    if (surveyNotificationsLoading) {
        return (
            <div className="flex flex-col gap-1.5">
                {Array.from({ length: 2 }).map((_, i) => (
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

    if (surveyNotifications.length === 0) {
        return (
            <section className="flex flex-col items-center gap-5 px-6 py-12 text-center">
                <MailHog className="h-32 w-auto" />
                <div className="flex flex-col gap-1.5 max-w-md">
                    <h3 className="m-0 text-base font-semibold">Get notified when responses land</h3>
                    <p className="m-0 text-sm text-muted">
                        Pipe survey responses straight into Slack, Discord, Microsoft Teams, or any webhook.
                    </p>
                </div>
                <div className="flex flex-wrap items-center justify-center gap-2">
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={() => openDialog()}
                        data-attr="survey-new-notification"
                        disabledReason={addDisabledReason}
                    >
                        Add notification
                    </LemonButton>
                    {renderCopyControl('secondary')}
                </div>
            </section>
        )
    }

    const headerActions = (
        <div className={buttonFullWidth ? 'flex flex-col gap-2' : 'flex flex-wrap gap-2'}>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconPlus />}
                onClick={() => openDialog()}
                fullWidth={buttonFullWidth}
                data-attr="survey-new-notification"
                disabledReason={addDisabledReason}
            >
                Add notification
            </LemonButton>
            {renderCopyControl('secondary')}
        </div>
    )

    return (
        <div className="flex flex-col gap-3">
            {buttonFullWidth ? (
                <>
                    {description ? <p className="m-0 text-sm text-muted">{description}</p> : null}
                    {headerActions}
                </>
            ) : (
                <div className="flex flex-wrap items-start justify-between gap-2">
                    {description ? (
                        <p className="m-0 text-sm text-muted flex-1 min-w-0">{description}</p>
                    ) : (
                        <div className="flex-1" />
                    )}
                    {headerActions}
                </div>
            )}
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
                                    onClick={() => openDialog({ notification: fn, intent: 'edit' })}
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
                            />
                            <ConfirmDeleteButton
                                onDelete={() => deleteSurveyNotification(fn)}
                                data-attr="survey-notification-tab-delete"
                            />
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
