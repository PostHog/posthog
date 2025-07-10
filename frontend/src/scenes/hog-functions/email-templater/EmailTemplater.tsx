import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import EmailEditor from 'react-email-editor'

import { LemonButton, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { capitalizeFirstLetter } from 'lib/utils'

import { EmailTemplaterLogicProps, emailTemplaterLogic } from './emailTemplaterLogic'

function EmailTemplaterForm({ mode }: { mode: 'full' | 'preview' }): JSX.Element {
    const { unlayerEditorProjectId, logicProps, appliedTemplate, templates, templatesLoading, mergeTags } =
        useValues(emailTemplaterLogic)
    const { setEmailEditorRef, onEmailEditorReady, setIsModalOpen, applyTemplate } = useActions(emailTemplaterLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const isMessagingTemplatesEnabled = featureFlags[FEATURE_FLAGS.MESSAGING]

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
                className="flex flex-1 flex-col overflow-hidden rounded border"
                logic={emailTemplaterLogic}
                props={logicProps}
                formKey="emailTemplate"
            >
                {(logicProps.emailMetaFields || ['from', 'to', 'subject']).map((field) => (
                    <LemonField
                        key={field}
                        name={field}
                        className="shrink-0 gap-1 border-b pl-2"
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
                                    globals={logicProps.variables}
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
                        minHeight={20}
                        options={{
                            mergeTags,
                            displayMode: 'email',
                            features: {
                                preview: true,
                                imageEditor: true,
                                stockImages: false,
                            },
                            projectId: unlayerEditorProjectId,
                        }}
                    />
                ) : (
                    <LemonField name="html" className="relative flex flex-col">
                        {({ value }) => (
                            <>
                                <div className="absolute inset-0 flex items-end justify-center p-2 opacity-0 transition-opacity hover:opacity-100">
                                    <div className="bg-surface-primary absolute inset-0 opacity-50" />
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

function EmailTemplaterModal(): JSX.Element {
    const { isModalOpen, isEmailEditorReady, emailTemplateChanged } = useValues(emailTemplaterLogic)
    const { closeWithConfirmation, submitEmailTemplate } = useActions(emailTemplaterLogic)

    return (
        <LemonModal
            isOpen={isModalOpen}
            width="90vw"
            onClose={() => closeWithConfirmation()}
            hasUnsavedInput={emailTemplateChanged}
        >
            <div className="flex h-[80vh]">
                <div className="flex flex-1 flex-col">
                    <div className="shrink-0">
                        <h2>Editing email template</h2>
                    </div>
                    <EmailTemplaterForm mode="full" />
                    <div className="mt-2 flex items-center gap-2">
                        <div className="flex-1" />
                        <LemonButton onClick={() => closeWithConfirmation()}>Discard changes</LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => submitEmailTemplate()}
                            disabledReason={isEmailEditorReady ? undefined : 'Loading email editor...'}
                        >
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
        <BindLogic logic={emailTemplaterLogic} props={props}>
            <div className="flex flex-1 flex-col">
                <EmailTemplaterForm mode="preview" />
                <EmailTemplaterModal />
            </div>
        </BindLogic>
    )
}
