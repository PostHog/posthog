import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useRef } from 'react'

import { IconBug, IconInfo, IconQuestion } from '@posthog/icons'
import {
    LemonBanner,
    LemonInput,
    LemonSegmentedButton,
    LemonSegmentedButtonOption,
    Link,
    Tooltip,
    lemonToast,
} from '@posthog/lemon-ui'

import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { IconFeedback } from 'lib/lemon-ui/icons'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import {
    SEVERITY_LEVEL_TO_NAME,
    SUPPORT_TICKET_TEMPLATES,
    SupportTicketKind,
    TARGET_AREA_TO_NAME,
    supportLogic,
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
    // only allow authentication issues for logged out users

    const dropRef = useRef<HTMLDivElement>(null)

    const handlePaste = (e: React.ClipboardEvent<HTMLDivElement>): void => {
        const items = e.clipboardData?.items
        if (!items) {
            return
        }

        // Convert DataTransferItemList to array for iteration
        const itemsArray = Array.from(items)
        for (const item of itemsArray) {
            if (item.type.startsWith('image/')) {
                const file = item.getAsFile()
                if (file) {
                    setFilesToUpload([...filesToUpload, file])
                }
            }
        }
    }

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url, fileName) => {
            setSendSupportRequestValue('message', sendSupportRequest.message + `\n\nAttachment "${fileName}": ${url}`)
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    const changeKind = (kind: SupportTicketKind): void => {
        setSendSupportRequestValue('kind', kind)
        if (kind === 'bug') {
            setSendSupportRequestValue('severity_level', 'medium')
        } else {
            setSendSupportRequestValue('severity_level', 'low')
        }
    }

    return (
        <Form
            logic={supportLogic}
            formKey="sendSupportRequest"
            id="support-modal-form"
            enableFormOnSubmit
            className="deprecated-space-y-4"
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
                <LemonSegmentedButton onChange={changeKind} fullWidth options={SUPPORT_TICKET_OPTIONS} />
            </LemonField>
            <LemonField name="target_area" label="Topic">
                <LemonSelect
                    disabledReason={
                        !user
                            ? 'Please login to your account before opening a ticket unrelated to authentication issues.'
                            : null
                    }
                    fullWidth
                    options={TARGET_AREA_TO_NAME}
                />
            </LemonField>
            {sendSupportRequest.target_area === 'error_tracking' && (
                <LemonBanner type="warning">
                    This topic is for our Error Tracking <i>product</i>. If you're reporting an error in PostHog please
                    choose the relevant topic so your submission is sent to the correct team.
                </LemonBanner>
            )}
            <LemonField
                name="message"
                label={sendSupportRequest.kind ? SUPPORT_TICKET_KIND_TO_PROMPT[sendSupportRequest.kind] : 'Content'}
            >
                {(props) => (
                    <div ref={dropRef} className="flex flex-col gap-2" onPaste={handlePaste}>
                        <LemonTextArea
                            placeholder={SUPPORT_TICKET_TEMPLATES[sendSupportRequest.kind] ?? 'Type your message here'}
                            data-attr="support-form-content-input"
                            minRows={5}
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
                    <Link
                        target="_blank"
                        disableDocsPanel
                        to="https://posthog.com/docs/support-options#severity-levels"
                    >
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
