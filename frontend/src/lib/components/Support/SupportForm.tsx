import {
    LemonBanner,
    LemonInput,
    LemonSegmentedButton,
    LemonSegmentedButtonOption,
    lemonToast,
    Link,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { IconBugReport, IconFeedback, IconHelpOutline } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import posthog from 'posthog-js'
import { useEffect, useRef } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { SEVERITY_LEVEL_TO_NAME, supportLogic, SupportTicketKind, TARGET_AREA_TO_NAME } from './supportLogic'

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

    useEffect(() => {
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
            <LemonField name="kind" label="What type of message is this?">
                <LemonSegmentedButton fullWidth options={SUPPORT_TICKET_OPTIONS} />
            </LemonField>
            <LemonField name="target_area" label="What area does this best relate to?">
                <LemonSelect
                    fullWidth
                    options={Object.entries(TARGET_AREA_TO_NAME).map(([key, value]) => ({
                        label: value,
                        value: key,
                        'data-attr': `support-form-target-area-${key}`,
                    }))}
                />
            </LemonField>
            {posthog.getFeatureFlag('show-troubleshooting-docs-in-support-form') === 'test-replay-banner' &&
                sendSupportRequest.target_area === 'session_replay' && (
                    <LemonBanner type="info">
                        <>
                            We're pretty proud of our docs. Check out these helpful links:
                            <ul>
                                <li>
                                    <Link target="_blank" to="https://posthog.com/docs/session-replay/troubleshooting">
                                        Session replay troubleshooting
                                    </Link>
                                </li>
                                <li>
                                    <Link
                                        target="_blank"
                                        to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record"
                                    >
                                        How to control which sessions you record
                                    </Link>
                                </li>
                            </ul>
                        </>
                    </LemonBanner>
                )}
            {posthog.getFeatureFlag('show-troubleshooting-docs-in-support-form') === 'test-replay-banner' &&
                sendSupportRequest.target_area === 'toolbar' && (
                    <LemonBanner type="info">
                        <>
                            We're pretty proud of our docs.{' '}
                            <Link target="_blank" to="https://posthog.com/docs/toolbar#troubleshooting-and-faq">
                                Check out this troubleshooting guide
                            </Link>
                        </>
                    </LemonBanner>
                )}
            <LemonField name="severity_level" label="What is the severity of this issue?">
                <LemonSelect
                    fullWidth
                    options={Object.entries(SEVERITY_LEVEL_TO_NAME).map(([key, value]) => ({
                        label: value,
                        value: key,
                    }))}
                />
            </LemonField>
            <span className="text-muted">
                Check out the{' '}
                <Link target="_blank" to="https://posthog.com/docs/support-options#severity-levels">
                    severity level definitions
                </Link>
                .
            </span>
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
        </Form>
    )
}
