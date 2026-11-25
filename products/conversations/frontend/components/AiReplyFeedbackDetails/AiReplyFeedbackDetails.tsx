import { useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { AiFeedbackReasonEnumApi } from '../../generated/api.schemas'

export interface AiReplyFeedbackDetailsProps {
    disabledReason?: string
    onSubmit: (feedbackText?: string, reasons?: AiFeedbackReasonEnumApi[]) => void
}

const REASON_LABELS: Record<AiFeedbackReasonEnumApi, string> = {
    [AiFeedbackReasonEnumApi.WrongFacts]: 'Wrong facts',
    [AiFeedbackReasonEnumApi.MissedQuestion]: 'Missed the question',
    [AiFeedbackReasonEnumApi.TooVague]: 'Too vague',
    [AiFeedbackReasonEnumApi.WrongTone]: 'Wrong tone',
    [AiFeedbackReasonEnumApi.ShouldNotRun]: 'Should not have run',
}

const REASONS = Object.keys(REASON_LABELS) as AiFeedbackReasonEnumApi[]

export function AiReplyFeedbackDetails({ disabledReason, onSubmit }: AiReplyFeedbackDetailsProps): JSX.Element {
    const [reasons, setReasons] = useState<AiFeedbackReasonEnumApi[]>([])
    const [feedbackText, setFeedbackText] = useState('')
    const trimmedText = feedbackText.trim()
    const hasDetails = reasons.length > 0 || !!trimmedText

    function toggleReason(reason: AiFeedbackReasonEnumApi): void {
        setReasons((current) =>
            current.includes(reason) ? current.filter((item) => item !== reason) : [...current, reason]
        )
    }

    function submit(): void {
        if (disabledReason || !hasDetails) {
            return
        }
        onSubmit(trimmedText || undefined, reasons.length > 0 ? reasons : undefined)
    }

    return (
        <div className="space-y-1.5">
            <div className="text-xs text-muted-alt">What was wrong? Pick any that apply.</div>
            <div className="flex flex-wrap gap-1">
                {REASONS.map((reason) => (
                    <LemonButton
                        key={reason}
                        type="secondary"
                        size="xsmall"
                        active={reasons.includes(reason)}
                        disabledReason={disabledReason}
                        onClick={() => toggleReason(reason)}
                        data-attr={`ai-reply-feedback-reason-${reason}`}
                    >
                        {REASON_LABELS[reason]}
                    </LemonButton>
                ))}
            </div>
            <div className="flex w-full gap-1.5 items-center">
                <LemonInput
                    placeholder="Add details (optional)"
                    fullWidth
                    size="small"
                    value={feedbackText}
                    onChange={setFeedbackText}
                    onPressEnter={submit}
                    disabledReason={disabledReason}
                />
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={submit}
                    disabledReason={disabledReason ?? (!hasDetails ? 'Pick a reason or add details' : undefined)}
                    data-attr="ai-reply-feedback-submit"
                >
                    Send
                </LemonButton>
            </div>
        </div>
    )
}
