import { IconBug, IconInfo, IconQuestion } from '@posthog/icons'
import {
    LemonInput,
    LemonSegmentedButton,
    LemonSegmentedButtonOption,
    lemonToast,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { IconFeedback } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { useEffect, useRef } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import {
    SEVERITY_LEVEL_TO_NAME,
    SUPPORT_TICKET_TEMPLATES,
    supportLogic,
    SupportTicketKind,
    TARGET_AREA_TO_NAME,
} from './supportLogic'

const SUPPORT_TICKET_OPTIONS: LemonSegmentedButtonOption<SupportTicketKind>[] = [
    {
        value: 'support',
        label: 'Question',
        icon: <IconQuestion />,
    },
    {
        value: 'feedback',
        label: 'Feedback',
        icon: <IconFeedback />,
    },
    {
        value: 'bug',
        label: 'Bug',
        icon: <IconBug />,
    },
]

const SUPPORT_TICKET_KIND_TO_PROMPT: Record<SupportTicketKind, string> = {
    bug: "What's the bug?",
    feedback: 'What feedback do you have?',
    support: 'What can we help you with?',
}

export function SupportForm(): JSX.Element | null {
    const { sendSupportRequest } = useValues(supportLogic)
    const { setSendSupportRequestValue } = useActions(supportLogic)
    const { objectStorageAvailable } = useValues(preflightLogic)
    // the support model can be shown when logged out, file upload is not offered to anonymous users
    const { user } = useValues(userLogic)

    const dropRef = useRef<HTMLDivElement>(null)

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url, fileName) => {
            setSendSupportRequestValue('message', sendSupportRequest.message + `\n\nAttachment "${fileName}": ${url}`)
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    const handleReportTypeChange = (kind: string = supportLogic.values.sendSupportRequest.kind ?? ''): void => {
        const message = supportLogic.values.sendSupportRequest.message

        // do not overwrite modified message
        if (
            !(
                message === SUPPORT_TICKET_TEMPLATES.bug ||
                message === SUPPORT_TICKET_TEMPLATES.feedback ||
                message === SUPPORT_TICKET_TEMPLATES.support ||
                !message
            )
        ) {
            return
        }

        if (kind === 'bug') {
            supportLogic.values.sendSupportRequest.message = SUPPORT_TICKET_TEMPLATES.bug
        } else if (kind === 'feedback') {
            supportLogic.values.sendSupportRequest.message = SUPPORT_TICKET_TEMPLATES.feedback
        } else if (kind === 'support') {
            supportLogic.values.sendSupportRequest.message = SUPPORT_TICKET_TEMPLATES.support
        }
    }

    useEffect(() => {
        handleReportTypeChange()
        if (sendSupportRequest.kind === 'bug') {
            setSendSupportRequestValue('severity_level', 'medium')
        } else {
            setSendSupportRequestValue('severity_level', 'low')
        }
    }, [sendSupportRequest.kind])

    return (
        <Form
            logic={supportLogic}
            formKey="sendSupportRequest"
            id="support-modal-form"
            enableFormOnSubmit
            className="space-y-4"
        >
            {!user && (
                <>
                    <LemonField name="name" label="Name">
                        <LemonInput data-attr="name" placeholder="Jane" />
                    </LemonField>
                    <LemonField name="email" label="Email">
                        <LemonInput data-attr="email" placeholder="your@email.com" />
                    </LemonField>
                </>
            )}
            <LemonField name="kind" label="Message type">
                <LemonSegmentedButton fullWidth options={SUPPORT_TICKET_OPTIONS} />
            </LemonField>
            <LemonField name="target_area" label="Topic">
                <LemonSelect fullWidth options={TARGET_AREA_TO_NAME} />
            </LemonField>
            <LemonField
                name="message"
                label={sendSupportRequest.kind ? SUPPORT_TICKET_KIND_TO_PROMPT[sendSupportRequest.kind] : 'Content'}
            >
                {(props) => (
                    <div ref={dropRef} className="flex flex-col gap-2">
                        <LemonTextArea
                            placeholder="Type your message here"
                            data-attr="support-form-content-input"
                            {...props}
                        />
                        {objectStorageAvailable && !!user && (
                            <LemonFileInput
                                accept="image/*"
                                multiple={false}
                                alternativeDropTargetRef={dropRef}
                                onChange={setFilesToUpload}
                                loading={uploading}
                                value={filesToUpload}
                            />
                        )}
                    </div>
                )}
            </LemonField>
            <div className="flex gap-2 flex-col">
                <div className="flex justify-between items-center">
                    <label className="LemonLabel">
                        Severity level
                        <Tooltip title="Severity levels help us prioritize your request.">
                            <span>
                                <IconInfo className="opacity-75" />
                            </span>
                        </Tooltip>
                    </label>
                    <Link target="_blank" to="https://posthog.com/docs/support-options#severity-levels">
                        Definitions
                    </Link>
                </div>
                <LemonField name="severity_level">
                    <LemonSelect
                        fullWidth
                        options={Object.entries(SEVERITY_LEVEL_TO_NAME).map(([key, value]) => ({
                            label: value,
                            value: key,
                        }))}
                    />
                </LemonField>
            </div>
        </Form>
    )
}
