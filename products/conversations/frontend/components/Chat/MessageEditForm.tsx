import { JSONContent } from '@tiptap/core'
import { useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { RichContentEditorType } from 'lib/components/RichContentEditor/types'

import type { ChatMessage } from '../../types'
import { SupportEditor, serializeToMarkdown } from '../Editor'

export interface MessageEditFormProps {
    message: ChatMessage
    saving: boolean
    onCancel: () => void
    onSave: (content: string, richContent: JSONContent) => void
}

/** Notes written through the ticket reply API, and ones carried in by an import, have no rich
 * content, so seed the editor from the plain text rather than opening it empty over a note that
 * clearly has a body. */
function initialContentFor(message: ChatMessage): JSONContent {
    if (message.richContent) {
        return message.richContent as JSONContent
    }
    return {
        type: 'doc',
        content: [
            {
                type: 'paragraph',
                content: message.content ? [{ type: 'text', text: message.content }] : [],
            },
        ],
    }
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
        onSave(serializeToMarkdown(richContent), richContent)
    }

    return (
        <div
            className="space-y-2"
            onKeyDown={(e) => {
                if (e.key === 'Escape') {
                    // The editor is nested inside the thread, so stop the key here rather than
                    // letting it reach whatever else treats Escape as dismiss.
                    e.stopPropagation()
                    onCancel()
                }
            }}
        >
            <SupportEditor
                initialContent={initialContentFor(message)}
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
