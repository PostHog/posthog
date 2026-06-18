import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

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
                    <LemonButton type="primary" onClick={handleSubmit} loading={composingLoading}>
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
            </div>
        </LemonModal>
    )
}
