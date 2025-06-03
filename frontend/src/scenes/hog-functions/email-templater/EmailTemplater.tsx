import { LemonButton, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { capitalizeFirstLetter } from 'lib/utils'
import EmailEditor from 'react-email-editor'

import { emailTemplaterLogic, EmailTemplaterLogicProps } from './emailTemplaterLogic'

function EmailTemplaterForm({
    mode,
    emailMetaFields,
    ...props
}: EmailTemplaterLogicProps & {
    mode: 'full' | 'preview'
}): JSX.Element {
    const logic = emailTemplaterLogic(props)
    const { setEmailEditorRef, onEmailEditorReady, setIsModalOpen, applyTemplate } = useActions(logic)
    const { appliedTemplate, templates, templatesLoading, mergeTags } = useValues(logic)

    const { featureFlags } = useValues(featureFlagLogic)
    const isMessagingTemplatesEnabled = featureFlags[FEATURE_FLAGS.MESSAGING_LIBRARY]

    return (
        <>
            {isMessagingTemplatesEnabled && templates.length > 0 && (
                <LemonSelect
                    className="mb-2"
                    placeholder="Start from a template (optional)"
                    loading={templatesLoading}
                    value={appliedTemplate?.id}
                    options={templates.map((template) => ({
                        label: template.name,
                        value: template.id,
                    }))}
                    onChange={(id) => {
                        const template = templates.find((t) => t.id === id)
                        if (template) {
                            applyTemplate(template)
                        }
                    }}
                    data-attr="email-template-selector"
                />
            )}
            <Form
                className="flex overflow-hidden flex-col flex-1 rounded border"
                logic={emailTemplaterLogic}
                props={props}
                formKey="emailTemplate"
            >
                {(emailMetaFields || ['from', 'to', 'subject']).map((field) => (
                    <LemonField
                        key={field}
                        name={field}
                        className="gap-1 pl-2 border-b shrink-0"
                        // We will handle the error display ourselves
                        renderError={() => null}
                    >
                        {({ value, onChange, error }) => (
                            <div className="flex items-center">
                                <LemonLabel className={error ? 'text-danger' : ''}>
                                    {capitalizeFirstLetter(field)}
                                </LemonLabel>
                                <CodeEditorInline
                                    embedded
                                    className="flex-1"
                                    globals={props.variables}
                                    value={value}
                                    onChange={onChange}
                                />
                            </div>
                        )}
                    </LemonField>
                ))}

                {mode === 'full' ? (
                    <EmailEditor
                        ref={(r) => setEmailEditorRef(r)}
                        onReady={() => onEmailEditorReady()}
                        options={{
                            mergeTags,
                            displayMode: 'email',
                            features: {
                                preview: true,
                                imageEditor: true,
                                stockImages: false,
                            },
                        }}
                    />
                ) : (
                    <LemonField name="html" className="flex relative flex-col">
                        {({ value }) => (
                            <>
                                <div className="flex absolute inset-0 justify-center items-end p-2 opacity-0 transition-opacity hover:opacity-100">
                                    <div className="absolute inset-0 opacity-50 bg-surface-primary" />
                                    <LemonButton type="primary" size="small" onClick={() => setIsModalOpen(true)}>
                                        Click to modify content
                                    </LemonButton>
                                </div>

                                <iframe srcDoc={value} className="flex-1" />
                            </>
                        )}
                    </LemonField>
                )}
            </Form>
        </>
    )
}

export function EmailTemplaterModal({ ...props }: EmailTemplaterLogicProps): JSX.Element {
    const { isModalOpen } = useValues(emailTemplaterLogic(props))
    const { setIsModalOpen, submitEmailTemplate } = useActions(emailTemplaterLogic(props))

    return (
        <LemonModal isOpen={isModalOpen} width="90vw" onClose={() => setIsModalOpen(false)}>
            <div className="h-[80vh] flex">
                <div className="flex flex-col flex-1">
                    <div className="shrink-0">
                        <h2>Editing email template</h2>
                    </div>
                    <EmailTemplaterForm {...props} mode="full" />
                    <div className="flex gap-2 items-center mt-2">
                        <div className="flex-1" />
                        <LemonButton onClick={() => setIsModalOpen(false)}>Cancel</LemonButton>
                        <LemonButton type="primary" onClick={() => submitEmailTemplate()}>
                            Save
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}

export function EmailTemplater(props: EmailTemplaterLogicProps): JSX.Element {
    return (
        <div className="flex flex-col flex-1">
            <EmailTemplaterForm {...props} mode="preview" />
            <EmailTemplaterModal {...props} />
        </div>
    )
}
