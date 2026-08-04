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
    /** Blocks saving regardless of what was typed, e.g. once a newer note has superseded this one. */
    saveDisabledReason?: string
    onCancel: () => void
    onSave: (content: string, richContent: JSONContent) => void
}

export function initialEditorContent(message: ChatMessage): JSONContent {
    return message.richContent ? (message.richContent as JSONContent) : messageBodyToRichContent(message.content)
}

/** What the editor currently holds, in both shapes the save sends. */
interface EditorBody {
    markdown: string
    richContent: string
}

function readBody(editor: RichContentEditorType): EditorBody {
    const doc = editor.getJSON()
    return { markdown: serializeToMarkdown(doc), richContent: JSON.stringify(doc) }
}

export function MessageEditForm({
    message,
    saving,
    saveDisabledReason,
    onCancel,
    onSave,
}: MessageEditFormProps): JSX.Element {
    const [isUploading, setIsUploading] = useState(false)
    const editorRef = useRef<RichContentEditorType | null>(null)
    // Compared against what the editor holds now, so "unchanged" means unchanged since it opened.
    // Comparing against the stored body instead would count the editor's own markdown escaping as an
    // edit, marking an untouched note as edited.
    const initialBodyRef = useRef<EditorBody | null>(null)
    const [body, setBody] = useState<EditorBody | null>(null)

    const unchanged =
        !!body &&
        !!initialBodyRef.current &&
        body.markdown === initialBodyRef.current.markdown &&
        body.richContent === initialBodyRef.current.richContent

    const blockedReason =
        saveDisabledReason ??
        (saving
            ? 'Saving...'
            : !body?.markdown.trim()
              ? "Note can't be empty"
              : isUploading
                ? 'Uploading image...'
                : unchanged
                  ? 'No changes to save'
                  : undefined)

    const handleSave = (): void => {
        if (blockedReason || !editorRef.current) {
            return
        }
        const richContent = editorRef.current.getJSON()
        onSave(serializeToMarkdown(richContent), richContent)
    }

    // The editor binds its Cmd+Enter handler once, on creation, so calling through a ref is what
    // keeps the shortcut using current state rather than the first render's.
    const handleSaveRef = useRef(handleSave)
    handleSaveRef.current = handleSave

    return (
        <div
            className="space-y-2"
            onKeyDown={(e) => {
                if (e.key !== 'Escape' || saving) {
                    return
                }
                // The editor's own popups (mentions, emoji, link) consume Escape to close themselves,
                // and a CJK IME consumes it to abort a composition. Cancelling on those would throw
                // away the whole rewrite when the user only meant to dismiss a popup.
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
                    const initial = readBody(editor)
                    initialBodyRef.current = initial
                    setBody(initial)
                    editor.focus('end')
                }}
                onUpdate={() => setBody(editorRef.current ? readBody(editorRef.current) : null)}
                onPressCmdEnter={() => handleSaveRef.current()}
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
                    disabledReason={blockedReason}
                    sideIcon={<KeyboardShortcut command enter />}
                    data-attr="save-edit-private-note"
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
