import { LemonButton, LemonLabel, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import EmailEditor from 'react-email-editor'

import { emailTemplaterLogic, EmailTemplaterLogicProps } from './emailTemplaterLogic'

function EmailTemplaterForm({
    mode,
    ...props
}: EmailTemplaterLogicProps & {
    mode: 'full' | 'preview'
}): JSX.Element {
    const { setEmailEditorRef, emailEditorReady, setIsModalOpen } = useActions(emailTemplaterLogic(props))

    return (
        <div className="flex flex-col border rounded overflow-hidden flex-1">
            <div className="flex items-center border-b shrink-0 gap-1 pl-2">
                <LemonLabel>From</LemonLabel>
                <CodeEditorInline embedded className="flex-1" globals={props.globals} />
            </div>
            <div className="flex items-center border-b shrink-0 gap-1 pl-2">
                <LemonLabel>To</LemonLabel>
                <CodeEditorInline embedded className="flex-1" globals={props.globals} />
            </div>
            <div className="flex items-center border-b shrink-0 gap-1 pl-2">
                <LemonLabel>Subject</LemonLabel>
                <CodeEditorInline embedded className="flex-1" globals={props.globals} />
            </div>

            {mode === 'full' ? (
                <EmailEditor ref={(r) => setEmailEditorRef(r)} onReady={() => emailEditorReady()} />
            ) : (
                <div className="relative flex flex-col">
                    <div className="absolute inset-0 flex items-center justify-center transition-opacity opacity-0 hover:opacity-100">
                        <div className="opacity-50 bg-bg-light absolute inset-0" />
                        <LemonButton type="secondary" onClick={() => setIsModalOpen(true)}>
                            Change content
                        </LemonButton>
                    </div>

                    <iframe srcDoc={props.value?.html} className="flex-1" />
                </div>
            )}
        </div>
    )
}

export function EmailTemplaterModal({ ...props }: EmailTemplaterLogicProps): JSX.Element {
    const { isModalOpen } = useValues(emailTemplaterLogic(props))
    const { setIsModalOpen, onSave } = useActions(emailTemplaterLogic(props))

    return (
        <LemonModal isOpen={isModalOpen} width="90vw" onClose={() => setIsModalOpen(false)}>
            <div className="h-[80vh] flex">
                <div className="flex flex-col flex-1">
                    <div className="shrink-0">
                        <h2>Editing template</h2>
                    </div>
                    <EmailTemplaterForm {...props} mode="full" />
                    <div className="flex items-center mt-2 gap-2">
                        <div className="flex-1" />
                        <LemonButton onClick={() => setIsModalOpen(false)}>Cancel</LemonButton>
                        <LemonButton type="primary" onClick={() => onSave()}>
                            Save
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}

export function EmailTemplater(props: EmailTemplaterLogicProps): JSX.Element {
    const {} = useValues(emailTemplaterLogic(props))

    return (
        <div className="flex flex-col flex-1">
            <EmailTemplaterForm {...props} mode="preview" />
            <EmailTemplaterModal {...props} />
        </div>
    )
}
