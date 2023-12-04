import { LemonInput, LemonSegmentedButton, LemonSegmentedButtonOption, lemonToast } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { IconBugReport, IconFeedback, IconHelpOutline } from 'lib/lemon-ui/icons'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { useRef } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { supportLogic, SupportTicketKind, TARGET_AREA_TO_NAME } from './supportLogic'

const SUPPORT_TICKET_OPTIONS: LemonSegmentedButtonOption<SupportTicketKind>[] = [
    {
        value: 'support',
        label: 'Question',
        icon: <IconHelpOutline />,
    },
    {
        value: 'feedback',
        label: 'Feedback',
        icon: <IconFeedback />,
    },
    {
        value: 'bug',
        label: 'Bug',
        icon: <IconBugReport />,
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

    return (
        <Form
            logic={supportLogic}
            formKey={'sendSupportRequest'}
            id="support-modal-form"
            enableFormOnSubmit
            className="space-y-4"
        >
            {!user && (
                <>
                    <Field name="name" label="Name">
                        <LemonInput data-attr="name" placeholder="Jane" />
                    </Field>
                    <Field name="email" label="Email">
                        <LemonInput data-attr="email" placeholder="your@email.com" />
                    </Field>
                </>
            )}
            <Field name="kind" label="What type of message is this?">
                <LemonSegmentedButton fullWidth options={SUPPORT_TICKET_OPTIONS} />
            </Field>
            <Field name="target_area" label="What area does this best relate to?">
                <LemonSelect
                    fullWidth
                    options={Object.entries(TARGET_AREA_TO_NAME).map(([key, value]) => ({
                        label: value,
                        value: key,
                    }))}
                />
            </Field>
            <Field
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
            </Field>
        </Form>
    )
}
