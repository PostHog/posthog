import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconLock } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'

import { SupportEditor, serializeToMarkdown } from '../Editor'
import { composeTicketLogic } from './composeTicketLogic'

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
    } = useValues(composeTicketLogic)
    const { closeComposeModal, setRecipientEmail, setEmailSubject, setEmailConfigId, submitCompose } =
        useActions(composeTicketLogic)

    const editorRef = useRef<RichContentEditorType | null>(null)
    const noteEditorRef = useRef<RichContentEditorType | null>(null)
    const verifiedEmailConfigs = emailConfigs.filter((c) => c.domain_verified)

    const emailConfigOptions = verifiedEmailConfigs.map((c) => ({
        value: c.id,
        label: (
            <span className="flex items-center gap-1">
                {`${c.from_name} <${c.from_email}>`}
                {c.is_default && <LemonTag type="primary">Primary</LemonTag>}
            </span>
        ),
    }))

    const handleSubmit = (): void => {
        const richContent = editorRef.current?.getJSON() ?? null
        const content = richContent ? serializeToMarkdown(richContent) : ''
        // The note is stored as markdown only. The thread renders and re-edits markdown-only
        // comments already, so it needs no rich content column of its own.
        const noteRichContent = noteEditorRef.current?.getJSON() ?? null
        const note = noteRichContent ? serializeToMarkdown(noteRichContent) : ''
        submitCompose(content, richContent as Record<string, unknown> | null, note)
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
                    <LemonButton type="primary" onClick={handleSubmit} loading={composingLoading}>
                        Send
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3 w-[500px] max-w-full">
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

                <div className="flex flex-col gap-1">
                    <label className="font-semibold text-xs flex items-center gap-1">
                        <IconLock className="text-sm" />
                        Private note (optional)
                    </label>
                    <SupportEditor
                        placeholder="Why you're reaching out, or anything the team should know"
                        onCreate={(editor) => {
                            noteEditorRef.current = editor
                        }}
                        onPressCmdEnter={handleSubmit}
                        minRows={2}
                    />
                    <span className="text-xs text-muted">
                        Only your team can see this. It is not sent to the recipient.
                    </span>
                </div>
            </div>
        </LemonModal>
    )
}
