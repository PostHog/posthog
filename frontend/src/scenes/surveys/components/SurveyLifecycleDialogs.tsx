import { useEffect, useState } from 'react'

import { LemonDialog, LemonDialogProps, lemonToast } from '@posthog/lemon-ui'

import { SurveyStartSchedulePicker } from 'scenes/surveys/components/SurveyStartSchedulePicker'

type ScheduleValue = string | undefined

type BaseSurveyScheduleDialogProps = {
    isOpen: boolean
    title: string
    description: string
    initialScheduledTime?: ScheduleValue
    defaultDatetimeValue?: () => string
    onSubmit: (scheduledTime: ScheduleValue) => Promise<void>
    onClose: () => void
    submitNowLabel: string
    submitScheduledLabel: string
    submitButtonStatus?: NonNullable<LemonDialogProps['primaryButton']>['status']
    errorToastMessage: string
}

function SurveyScheduleDialog(props: BaseSurveyScheduleDialogProps): JSX.Element | null {
    const {
        isOpen,
        title,
        description,
        initialScheduledTime,
        defaultDatetimeValue,
        onSubmit,
        onClose,
        submitNowLabel,
        submitScheduledLabel,
        submitButtonStatus,
        errorToastMessage,
    } = props

    const [scheduledTime, setScheduledTime] = useState<ScheduleValue>(undefined)

    useEffect(() => {
        if (isOpen) {
            setScheduledTime(initialScheduledTime)
        }
    }, [isOpen, initialScheduledTime])

    if (!isOpen) {
        return null
    }

    return (
        <LemonDialog
            title={title}
            onClose={onClose}
            onAfterClose={onClose}
            shouldAwaitSubmit
            content={
                <div>
                    <div className="text-sm text-secondary mb-4">{description}</div>
                    <SurveyStartSchedulePicker
                        value={scheduledTime}
                        onChange={setScheduledTime}
                        manualLabel="Immediately"
                        datetimeLabel="In the future"
                        defaultDatetimeValue={defaultDatetimeValue}
                    />
                </div>
            }
            primaryButton={
                {
                    children: scheduledTime ? submitScheduledLabel : submitNowLabel,
                    type: 'primary',
                    status: submitButtonStatus,
                    onClick: async () => {
                        try {
                            await onSubmit(scheduledTime)
                            onClose()
                        } catch {
                            lemonToast.error(errorToastMessage)
                        }
                    },
                    preventClosing: true,
                    size: 'small',
                } as LemonDialogProps['primaryButton']
            }
            secondaryButton={{
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            }}
        />
    )
}

export type SurveyResumeDialogProps = {
    isOpen: boolean
    description: string
    initialScheduledStartTime?: ScheduleValue
    defaultDatetimeValue?: () => string
    onSubmit: (scheduledStartTime: ScheduleValue) => Promise<void>
    onClose: () => void
}

export function SurveyResumeDialog(props: SurveyResumeDialogProps): JSX.Element | null {
    return (
        <SurveyScheduleDialog
            isOpen={props.isOpen}
            title="Resume this survey?"
            description={props.description}
            initialScheduledTime={props.initialScheduledStartTime}
            defaultDatetimeValue={props.defaultDatetimeValue}
            onSubmit={props.onSubmit}
            onClose={props.onClose}
            submitNowLabel="Resume"
            submitScheduledLabel="Schedule resume"
            errorToastMessage="Failed to resume survey. Please try again."
        />
    )
}

export type SurveyStopDialogProps = {
    isOpen: boolean
    description: string
    initialScheduledEndTime?: ScheduleValue
    defaultDatetimeValue?: () => string
    onSubmit: (scheduledEndTime: ScheduleValue) => Promise<void>
    onClose: () => void
}

export function SurveyStopDialog(props: SurveyStopDialogProps): JSX.Element | null {
    return (
        <SurveyScheduleDialog
            isOpen={props.isOpen}
            title="Stop this survey?"
            description={props.description}
            initialScheduledTime={props.initialScheduledEndTime}
            defaultDatetimeValue={props.defaultDatetimeValue}
            onSubmit={props.onSubmit}
            onClose={props.onClose}
            submitNowLabel="Stop"
            submitScheduledLabel="Schedule stop"
            submitButtonStatus="danger"
            errorToastMessage="Failed to stop survey. Please try again."
        />
    )
}
