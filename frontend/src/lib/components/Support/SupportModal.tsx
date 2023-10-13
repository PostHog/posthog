import { useActions, useValues } from 'kea'
import { SupportTicketKind, TARGET_AREA_TO_NAME, supportLogic } from './supportLogic'
import { Form } from 'kea-forms'
import { LemonButton } from 'lib/lemon-ui/LemonButton/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { LemonSelect, LemonSelectOptions } from 'lib/lemon-ui/LemonSelect/LemonSelect'
import { Field } from 'lib/forms/Field'
import { IconBugReport, IconFeedback, IconSupport } from 'lib/lemon-ui/icons'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { useEffect, useRef } from 'react'
import { LemonInput, lemonToast } from '@posthog/lemon-ui'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { userLogic } from 'scenes/userLogic'

const SUPPORT_TICKET_TEMPLATES = {
    bug: '## Bug description\n\n*Please describe.*\n*If this affects the front-end, screenshots and links would be of great help. This speeds up our ability to troubleshoot tremendously.*\n\n## How to reproduce\n\n1.\n2.\n3.\n\n## Additional context\n\n',
    feedback:
        "## Is your feature request related to a problem?\n\n*Please describe.*\n\n## Describe the solution you'd like\n\n\n\n## Describe alternatives you've considered\n\n\n\n## Additional context\n\n",
    support:
        '## How can we assist you?\n\n*Please describe your issue or question in detail.*\n\n## Steps to reproduce (if applicable)\n\n1.\n2.\n3.\n\n## Expected behavior\n\n\n## Actual behavior\n\n\n## Additional context\n\n',
}
const SUPPORT_TICKET_OPTIONS: LemonSelectOptions<SupportTicketKind> = [
    {
        value: 'bug',
        label: 'Bug',
        icon: <IconBugReport />,
    },
    {
        value: 'feedback',
        label: 'Feedback',
        icon: <IconFeedback />,
    },
    {
        value: 'support',
        label: 'Support',
        icon: <IconSupport />,
    },
]
const SUPPORT_TICKET_KIND_TO_TITLE: Record<SupportTicketKind, string> = {
    bug: 'Report a bug',
    feedback: 'Give feedback',
    support: 'Get support',
}
const SUPPORT_TICKET_KIND_TO_PROMPT: Record<SupportTicketKind, string> = {
    bug: "What's the bug?",
    feedback: 'What feedback do you have?',
    support: 'What can we help you with?',
}

export function SupportModal({ loggedIn = true }: { loggedIn?: boolean }): JSX.Element | null {
    const { sendSupportRequest, isSupportFormOpen, sendSupportLoggedOutRequest } = useValues(supportLogic)
    const { setSendSupportRequestValue, closeSupportForm } = useActions(supportLogic)
    const { objectStorageAvailable } = useValues(preflightLogic)
    // the support model can be shown when logged out, file upload is not offered to anonymous users
    const { user } = useValues(userLogic)

    useEffect(() => {
        handleReportTypeChange()
    }, [])

    if (!preflightLogic.values.preflight?.cloud) {
        if (isSupportFormOpen) {
            lemonToast.error(`In-app support isn't provided for self-hosted instances.`)
        }
        return null
    }
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
        if (kind === 'bug') {
            supportLogic.values.sendSupportRequest.message = SUPPORT_TICKET_TEMPLATES.bug
        } else if (kind === 'feedback') {
            supportLogic.values.sendSupportRequest.message = SUPPORT_TICKET_TEMPLATES.feedback
        } else if (kind === 'support') {
            supportLogic.values.sendSupportRequest.message = SUPPORT_TICKET_TEMPLATES.support
        }
    }

    return (
        <LemonModal
            isOpen={isSupportFormOpen}
            onClose={closeSupportForm}
            title={
                sendSupportRequest.kind
                    ? SUPPORT_TICKET_KIND_TO_TITLE[sendSupportRequest.kind]
                    : 'Leave a message with PostHog'
            }
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton form="support-modal-form" type="secondary" onClick={closeSupportForm}>
                        Cancel
                    </LemonButton>
                    <LemonButton form="support-modal-form" htmlType="submit" type="primary" data-attr="submit">
                        Submit
                    </LemonButton>
                </div>
            }
            hasUnsavedInput={loggedIn ? !!sendSupportRequest.message : !!sendSupportLoggedOutRequest.message}
        >
            <Form
                logic={supportLogic}
                formKey={loggedIn ? 'sendSupportRequest' : 'sendSupportLoggedOutRequest'}
                id="support-modal-form"
                enableFormOnSubmit
                className="space-y-4"
            >
                {!loggedIn && (
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
                    <LemonSelect onSelect={handleReportTypeChange} fullWidth options={SUPPORT_TICKET_OPTIONS} />
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
        </LemonModal>
    )
}
