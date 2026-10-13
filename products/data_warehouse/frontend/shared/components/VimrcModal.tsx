import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { VIMRC_MAX_LENGTH } from 'lib/monaco/vimrc'

import { sqlEditorVimLogic } from '../logics/sqlEditorVimLogic'

export function VimrcModal({ editorKey }: { editorKey: string }): JSX.Element {
    const { vimrcEditorKey, vimrcDraft, vimrcDraftErrors, vimrcTooLong, vimrcSaving } = useValues(sqlEditorVimLogic)
    const { closeVimrcModal, setVimrcDraft, saveVimrc } = useActions(sqlEditorVimLogic)

    return (
        <LemonModal
            title="Edit vimrc"
            description={
                <span>
                    These commands run each time Vim mode starts. Use map commands such as{' '}
                    <code>inoremap jj &lt;Esc&gt;</code>, and set commands such as <code>set cursorblink</code> or{' '}
                    <code>set relativenumber</code>. Lines that start with <code>"</code> are comments.
                </span>
            }
            isOpen={vimrcEditorKey === editorKey}
            onClose={closeVimrcModal}
            width={600}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeVimrcModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveVimrc}
                        loading={vimrcSaving}
                        disabledReason={
                            vimrcDraftErrors.length
                                ? 'Fix the lines listed above to save'
                                : vimrcTooLong
                                  ? `Keep the vimrc under ${VIMRC_MAX_LENGTH.toLocaleString()} characters to save`
                                  : undefined
                        }
                        data-attr="sql-editor-vimrc-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                <LemonTextArea
                    value={vimrcDraft}
                    onChange={setVimrcDraft}
                    placeholder={'inoremap jj <Esc>\nset cursorblink'}
                    className="font-mono"
                    minRows={8}
                    maxRows={20}
                    autoFocus
                    data-attr="sql-editor-vimrc-input"
                />
                {vimrcDraftErrors.length ? (
                    <ul className="text-danger text-xs flex flex-col gap-1">
                        {vimrcDraftErrors.map(({ lineNumber, message }) => (
                            <li key={lineNumber}>{`Line ${lineNumber}: ${message}`}</li>
                        ))}
                    </ul>
                ) : null}
            </div>
        </LemonModal>
    )
}
