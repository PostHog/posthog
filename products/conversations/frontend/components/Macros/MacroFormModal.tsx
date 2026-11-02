import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
import { markdownToHtml } from 'lib/utils/markdown'

import { serializeToMarkdown, SupportEditor } from '../Editor'
import { unescapeMacroTokens } from './renderMacro'
import { shortcutError, supportMacrosLogic } from './supportMacrosLogic'

const VARIABLES: { label: string; token: string }[] = [
    { label: 'Customer first name', token: '{{customer.first_name}}' },
    { label: 'Customer name', token: '{{customer.name}}' },
    { label: 'Customer email', token: '{{customer.email}}' },
    { label: 'Your first name', token: '{{agent.first_name}}' },
    { label: 'Your name', token: '{{agent.name}}' },
    { label: 'Ticket number', token: '{{ticket.number}}' },
]

export function MacroFormModal(): JSX.Element | null {
    const { macroDraft, macroSaving } = useValues(supportMacrosLogic)
    const { closeMacroDraft, setMacroDraftName, setMacroDraftShortcut, createMacro, updateMacro } =
        useActions(supportMacrosLogic)
    const editorRef = useRef<RichContentEditorType | null>(null)
    const draftKey = macroDraft ? (macroDraft.id ?? 'new') : ''
    const bodyEmptyDefault = !(macroDraft?.body ?? '').trim()
    const [bodyEmpty, setBodyEmpty] = useState(bodyEmptyDefault)
    const lastDraftKey = useRef(draftKey)
    if (lastDraftKey.current !== draftKey) {
        lastDraftKey.current = draftKey
        setBodyEmpty(bodyEmptyDefault)
    }

    if (!macroDraft) {
        return null
    }

    const save = (): void => {
        const editor = editorRef.current
        const serialized = editor ? serializeToMarkdown(editor.getJSON()) : macroDraft.body
        const body = unescapeMacroTokens(serialized).trim()
        if (!macroDraft.name.trim() || !body) {
            return
        }
        if (shortcutError(macroDraft.shortcut)) {
            return
        }
        const payload = { name: macroDraft.name, shortcut: macroDraft.shortcut, body }
        if (macroDraft.id) {
            updateMacro({ ...payload, id: macroDraft.id })
        } else {
            createMacro(payload)
        }
    }

    return (
        <LemonModal
            title={macroDraft.id ? 'Edit macro' : 'New macro'}
            isOpen
            onClose={closeMacroDraft}
            footer={
                <div className="flex justify-end gap-2">
                    <LemonButton type="secondary" onClick={closeMacroDraft} disabled={macroSaving}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={save}
                        loading={macroSaving}
                        disabledReason={
                            !macroDraft.name.trim()
                                ? 'Add a name'
                                : shortcutError(macroDraft.shortcut) || (bodyEmpty ? 'Write the reply' : undefined)
                        }
                        data-attr="support-macro-save"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-3">
                <LemonInput
                    fullWidth
                    value={macroDraft.name}
                    onChange={setMacroDraftName}
                    placeholder="Cancellation"
                    autoFocus
                />
                <LemonInput
                    fullWidth
                    value={macroDraft.shortcut}
                    onChange={setMacroDraftShortcut}
                    placeholder="cancel"
                    prefix={<span>/</span>}
                />
                <p className="mb-0 text-xs text-muted">
                    Letters, numbers, and hyphens. Leave this blank to keep the macro in the menu only. Agents insert it
                    by typing / followed by the shortcut.
                </p>
                <SupportEditor
                    key={macroDraft.id ?? 'new'}
                    initialContent={null}
                    minRows={6}
                    placeholder="Hi {{customer.first_name}}"
                    onUpdate={setBodyEmpty}
                    onCreate={(editor) => {
                        editorRef.current = editor
                        if (macroDraft.body) {
                            editor.setContent(markdownToHtml(macroDraft.body))
                        }
                    }}
                />
                <div className="flex flex-wrap gap-1">
                    {VARIABLES.map((variable) => (
                        <LemonButton
                            key={variable.token}
                            size="xsmall"
                            type="secondary"
                            onClick={() => editorRef.current?.insertContent(variable.token)}
                        >
                            {variable.label}
                        </LemonButton>
                    ))}
                </div>
            </div>
        </LemonModal>
    )
}
