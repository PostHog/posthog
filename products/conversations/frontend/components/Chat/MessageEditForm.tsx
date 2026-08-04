import { JSONContent } from '@tiptap/core'
import { useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { RichContentEditorType } from 'lib/components/RichContentEditor/types'

import type { ChatMessage } from '../../types'
import { SupportEditor, messageBodyToRichContent, serializeToMarkdown } from '../Editor'

export interface MessageEditFormProps {
    message: ChatMessage
    saving: boolean
    onCancel: () => void
    onSave: (content: string, richContent: JSONContent) => void
}

export function initialEditorContent(message: ChatMessage): JSONContent {
    return message.richContent ? (message.richContent as JSONContent) : messageBodyToRichContent(message.content)
}

export function MessageEditForm({ message, saving, onCancel, onSave }: MessageEditFormProps): JSX.Element {
    const [isEmpty, setIsEmpty] = useState(!message.content && !message.richContent)
    const [isUploading, setIsUploading] = useState(false)
    const editorRef = useRef<RichContentEditorType | null>(null)

    const saveBlockedReason = saving
        ? 'Saving...'
        : isEmpty
          ? "Note can't be empty"
          : isUploading
            ? 'Uploading image...'
            : undefined

    // Shared by the button and Cmd+Enter, which bypasses the button's disabled state.
    const handleSave = (): void => {
        if (saveBlockedReason || !editorRef.current) {
            return
        }
        const richContent = editorRef.current.getJSON()
        const content = serializeToMarkdown(richContent)
        // Whitespace survives the editor's own isEmpty check, and the backend accepts it, so a note
        // could be blanked by saving a space.
        if (!content.trim()) {
            return
        }
        // Saving an unchanged note would still round-trip its content and cost a request, so treat
        // it as a cancel instead.
        if (content === message.content) {
            onCancel()
            return
        }
        onSave(content, richContent)
    }

    return (
        <div
            className="space-y-2"
            onKeyDown={(e) => {
                if (e.key !== 'Escape' || saving) {
                    return
                }
                // The editor's own popups (mentions, emoji, link) consume Escape to close
                // themselves, and a CJK IME consumes it to abort a composition. Cancelling on those
                // would throw away the whole rewrite when the user only meant to dismiss a popup.
                if (e.defaultPrevented || e.nativeEvent.isComposing) {
                    return
                }
                e.stopPropagation()
                onCancel()
            }}
        >
            <SupportEditor
                initialContent={initialEditorContent(message)}
                placeholder="Edit your private note..."
                onCreate={(editor) => {
                    editorRef.current = editor
                    editor.focus('end')
                }}
                onUpdate={setIsEmpty}
                onPressCmdEnter={handleSave}
                onUploadingChange={setIsUploading}
                disabled={saving}
                minRows={3}
                // The editor carries a top margin for the composer, which sits below the thread.
                // Inside a note it reads as a stray gap.
                className="mt-0"
            />
            <div className="flex justify-end items-center gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={onCancel}
                    disabledReason={saving ? 'Saving...' : undefined}
                    data-attr="cancel-edit-private-note"
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={handleSave}
                    loading={saving}
                    disabledReason={saveBlockedReason}
                    sideIcon={<KeyboardShortcut command enter />}
                    data-attr="save-edit-private-note"
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
