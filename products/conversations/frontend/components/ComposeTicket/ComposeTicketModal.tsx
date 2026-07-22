import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconUpload } from '@posthog/icons'
import {
    LemonButton,
    LemonFileInput,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonSnack,
} from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'

import { SupportEditor, serializeToMarkdown } from '../Editor'
import { composeTicketLogic } from './composeTicketLogic'

// Stable identity so the controlled LemonFileInput resets after each pick (see MessageInput).
const NO_FILES: File[] = []

export function ComposeTicketModal(): JSX.Element | null {
    const {
        isOpen,
        recipientEmail,
        recipientDistinctId,
        emailSubject,
        emailConfigId,
        emailConfigs,
        emailConfigsLoading,
        composingLoading,
        cc,
        bcc,
        attachments,
        attachmentUploading,
    } = useValues(composeTicketLogic)
    const {
        closeComposeModal,
        setRecipientEmail,
        setEmailSubject,
        setEmailConfigId,
        submitCompose,
        setCc,
        setBcc,
        uploadAttachment,
        removeAttachment,
    } = useActions(composeTicketLogic)

    const editorRef = useRef<RichContentEditorType | null>(null)
    const verifiedEmailConfigs = emailConfigs.filter((c) => c.domain_verified)

    const emailConfigOptions = verifiedEmailConfigs.map((c) => ({
        value: c.id,
        label: `${c.from_name} <${c.from_email}>`,
    }))

    const handleSubmit = (): void => {
        const richContent = editorRef.current?.getJSON() ?? null
        const content = richContent ? serializeToMarkdown(richContent) : ''
        submitCompose(content, richContent as Record<string, unknown> | null)
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeComposeModal}
            title="New outbound ticket"
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeComposeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        loading={composingLoading}
                        disabledReason={attachmentUploading ? 'Uploading attachment...' : undefined}
                    >
                        Send
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3 min-w-[500px]">
                <div className="flex flex-col gap-1">
                    <label className="font-semibold text-xs">From</label>
                    <LemonSelect
                        value={emailConfigId || undefined}
                        options={emailConfigOptions}
                        onChange={(value) => value && setEmailConfigId(value)}
                        placeholder={emailConfigsLoading ? 'Loading...' : 'Select sender address...'}
                        loading={emailConfigsLoading}
                        fullWidth
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <label className="font-semibold text-xs">To</label>
                    <LemonInput
                        type="email"
                        value={recipientEmail}
                        onChange={setRecipientEmail}
                        placeholder="customer@example.com"
                        fullWidth
                        disabledReason={
                            recipientDistinctId && recipientEmail ? 'Email is linked to the selected person' : undefined
                        }
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <label className="font-semibold text-xs">Cc</label>
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={cc}
                        onChange={setCc}
                        placeholder="Add Cc recipients (optional)..."
                        fullWidth
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <label className="font-semibold text-xs">Bcc</label>
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={bcc}
                        onChange={setBcc}
                        placeholder="Add Bcc recipients (optional)..."
                        fullWidth
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <label className="font-semibold text-xs">Subject</label>
                    <LemonInput
                        value={emailSubject}
                        onChange={setEmailSubject}
                        placeholder="Email subject (optional)"
                        fullWidth
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <label className="font-semibold text-xs">Message</label>
                    <SupportEditor
                        placeholder="Type your message..."
                        onCreate={(editor) => {
                            editorRef.current = editor
                        }}
                        onPressCmdEnter={handleSubmit}
                        minRows={5}
                    />
                </div>

                <div className="flex flex-wrap items-center gap-1">
                    {attachments.map((attachment) => (
                        <LemonSnack key={attachment.id} onClose={() => removeAttachment(attachment.id)}>
                            {attachment.name}
                        </LemonSnack>
                    ))}
                    <LemonFileInput
                        accept="*/*"
                        multiple
                        value={NO_FILES}
                        showUploadedFiles={false}
                        loading={attachmentUploading}
                        onChange={(files) => uploadAttachment(files)}
                        callToAction={
                            <LemonButton
                                size="small"
                                type="tertiary"
                                icon={<IconUpload />}
                                loading={attachmentUploading}
                            >
                                Attach file
                            </LemonButton>
                        }
                    />
                </div>
            </div>
        </LemonModal>
    )
}
