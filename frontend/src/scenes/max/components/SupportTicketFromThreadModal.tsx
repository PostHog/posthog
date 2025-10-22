import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'

import { IconBug, IconInfo, IconQuestion } from '@posthog/icons'
import {
    LemonBanner,
    LemonSegmentedButton,
    LemonSegmentedButtonOption,
    LemonSelect,
    LemonTextArea,
} from '@posthog/lemon-ui'

import {
    SEVERITY_LEVEL_TO_NAME,
    SupportTicketKind,
    TARGET_AREA_TO_NAME,
    supportLogic,
} from 'lib/components/Support/supportLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'

interface SupportTicketFromThreadModalProps {
    /** Pre-filled data from Max AI */
    ticketData: {
        summary: string
        target_area: string
        priority: string
        source?: string
        created_via?: string
    }
    /** Callback when ticket is submitted */
    onSubmitted?: (ticketId?: string) => void
    /** Callback when ticket creation is cancelled */
    onCancelled?: () => void
    /** Ref to access submit function from parent */
    onSubmitRef?: (submitFn: () => Promise<void>) => void
}

const SUPPORT_TICKET_OPTIONS: LemonSegmentedButtonOption<SupportTicketKind>[] = [
    {
        value: 'support',
        label: 'Question',
        icon: <IconQuestion />,
    },
    {
        value: 'feedback',
        label: 'Feedback',
        icon: <IconInfo />,
    },
    {
        value: 'bug',
        label: 'Bug',
        icon: <IconBug />,
    },
]

export function SupportTicketFromThreadModal({
    ticketData,
    onSubmitted,
    onSubmitRef,
}: SupportTicketFromThreadModalProps): JSX.Element {
    const { sendSupportRequest } = useValues(supportLogic)
    const { setSendSupportRequestValue, resetSendSupportRequest, submitSendSupportRequest } = useActions(supportLogic)

    // Pre-fill the form with data from Max
    useEffect(() => {
        const formattedMessage = `Hi,

I've had a conversation with PostHog AI, here's the summary:

> ${ticketData.summary}

Thanks,`

        resetSendSupportRequest({
            kind: 'support', // Default to support ticket
            target_area: ticketData.target_area as any,
            severity_level:
                ticketData.priority === 'critical'
                    ? 'critical'
                    : ticketData.priority === 'high'
                      ? 'high'
                      : ticketData.priority === 'low'
                        ? 'low'
                        : 'medium',
            message: formattedMessage,
            name: '',
            email: '',
            tags: ['posthog_ai_escalated'],
        })
    }, [ticketData, resetSendSupportRequest])

    const handleSubmit = async (): Promise<void> => {
        try {
            await submitSendSupportRequest()
            onSubmitted?.()
        } catch (error) {
            console.error('Failed to submit support ticket:', error)
            throw error // Re-throw to let the button handle the error state
        }
    }

    // Expose submit function to parent
    useEffect(() => {
        onSubmitRef?.(handleSubmit)
    }, [onSubmitRef, handleSubmit])

    return (
        <div className="space-y-4">
            <p className="text-muted text-sm">
                Here's a draft support ticket with a summary of your conversation. You can review and submit it below:
            </p>

            <Form logic={supportLogic} formKey="sendSupportRequest" className="space-y-4" enableFormOnSubmit>
                <LemonField name="kind" label="What type of request is this?">
                    <LemonSegmentedButton
                        options={SUPPORT_TICKET_OPTIONS}
                        value={sendSupportRequest.kind}
                        onChange={(value) => setSendSupportRequestValue('kind', value)}
                        fullWidth
                    />
                </LemonField>

                <LemonField name="target_area" label="What area does this relate to?">
                    <LemonSelect
                        value={sendSupportRequest.target_area}
                        onChange={(value) => setSendSupportRequestValue('target_area', value)}
                        options={TARGET_AREA_TO_NAME}
                        placeholder="Select an area"
                    />
                </LemonField>

                <LemonField name="severity_level" label="How urgent is this?">
                    <LemonSelect
                        value={sendSupportRequest.severity_level}
                        onChange={(value) => setSendSupportRequestValue('severity_level', value)}
                        options={Object.entries(SEVERITY_LEVEL_TO_NAME).map(([key, value]) => ({
                            label: value,
                            value: key,
                        }))}
                        placeholder="Select urgency level"
                    />
                </LemonField>

                <LemonField name="message" label="Description">
                    <LemonTextArea
                        value={sendSupportRequest.message}
                        onChange={(value) => setSendSupportRequestValue('message', value)}
                        placeholder="Describe your issue..."
                        rows={8}
                    />
                </LemonField>
            </Form>

            <LemonBanner type="info">
                <div className="text-sm">
                    <strong>Note:</strong> Our support team will have access to the full conversation history to help
                    understand your issue.
                </div>
            </LemonBanner>
        </div>
    )
}
