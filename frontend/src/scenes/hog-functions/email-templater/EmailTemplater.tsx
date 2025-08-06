import { LemonButton, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import EmailEditor from 'react-email-editor'

import { emailTemplaterLogic, EmailTemplaterLogicProps } from './emailTemplaterLogic'

import { unsubscribeLinkToolCustomJs } from './custom-tools/unsubscribeLinkTool'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IconExternal } from '@posthog/icons'
import { urls } from 'scenes/urls'
import { IntegrationConfigureProps } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'

export type EmailEditorMode = 'full' | 'preview'

/**
 * email: basic email editor with free-text fields, used for configuring email platform realtime destinations
 * native_email: advanced editor with email integration dropdown, and additional email metafields
 * native_email-template: editor for creating reusable templates, with only subject and preheader, and email content fields
 */
export type EmailTemplaterType = 'email' | 'native_email' | 'native_email_template'
type EmailMetaFieldKey = 'from' | 'from_integration' | 'preheader' | 'to' | 'subject'
type EmailMetaField = {
    key: EmailMetaFieldKey
    label: string
    optional: boolean
    helpText?: string
    isAdvancedField?: boolean
}

const EMAIL_META_FIELDS = {
    FROM: { key: 'from', label: 'From', optional: false },
    FROM_INTEGRATION: {
        key: 'from_integration',
        label: 'From',
        optional: false,
    },
    PREHEADER: {
        key: 'preheader',
        label: 'Preheader',
        optional: true,
        helpText: 'This is the preview text that appears below the subject line in an inbox.',
    },
    TO: { key: 'to', label: 'To', optional: false },
    SUBJECT: { key: 'subject', label: 'Subject', optional: false },
} as const

const EMAIL_TYPE_SUPPORTED_FIELDS: Record<EmailTemplaterType, EmailMetaField[]> = {
    email: [EMAIL_META_FIELDS.FROM, EMAIL_META_FIELDS.TO, EMAIL_META_FIELDS.SUBJECT],
    native_email: [
        EMAIL_META_FIELDS.FROM_INTEGRATION,
        EMAIL_META_FIELDS.TO,
        EMAIL_META_FIELDS.SUBJECT,
        EMAIL_META_FIELDS.PREHEADER,
    ],
    native_email_template: [EMAIL_META_FIELDS.SUBJECT, EMAIL_META_FIELDS.PREHEADER],
} as const

function DestinationEmailTemplaterForm({ mode }: { mode: EmailEditorMode }): JSX.Element {
    const { logicProps, mergeTags } = useValues(emailTemplaterLogic)
    const { setEmailEditorRef, onEmailEditorReady, setIsModalOpen } = useActions(emailTemplaterLogic)

    return (
        <>
            <Form
                className="flex overflow-hidden flex-col flex-1 rounded border"
                logic={emailTemplaterLogic}
                props={logicProps}
                formKey="emailTemplate"
            >
                {EMAIL_TYPE_SUPPORTED_FIELDS[logicProps.type].map((field) => (
                    <LemonField
                        key={field.key}
                        name={field.key}
                        className="gap-1 pl-2 border-b shrink-0"
                        // We will handle the error display ourselves
                        renderError={() => null}
                    >
                        {({ value, onChange, error }) => (
                            <div className="flex items-center gap-2">
                                <LemonLabel
                                    className={error ? 'text-danger' : ''}
                                    info={field.helpText}
                                    showOptional={field.optional}
                                >
                                    {field.label}
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

function NativeEmailIntegrationChoice({ onChange, value }: IntegrationConfigureProps): JSX.Element {
    const { integrationsLoading, integrations } = useValues(integrationsLogic)

    const integrationsOfKind = integrations?.filter((x) => x.kind === 'email')

    if (!integrationsLoading && integrationsOfKind?.length === 0) {
        return (
            <div className="flex gap-2 items-center justify-end">
                <span className="text-muted">No email senders configured yet</span>
                <LemonButton
                    size="small"
                    type="tertiary"
                    to={urls.messaging('channels')}
                    targetBlank
                    className="m-1"
                    icon={<IconExternal />}
                >
                    Connect email sender
                </LemonButton>
            </div>
        )
    }

    return (
        <>
            <LemonSelect
                className="m-1"
                placeholder="Choose email sender"
                loading={integrationsLoading}
                options={(integrationsOfKind || []).map((integration) => ({
                    label: integration.display_name,
                    value: integration.id,
                }))}
                value={value}
                onChange={onChange}
            />
        </>
    )
}

function NativeEmailTemplaterForm({ mode }: { mode: EmailEditorMode }): JSX.Element {
    const { unlayerEditorProjectId, logicProps, appliedTemplate, templates, templatesLoading, mergeTags } =
        useValues(emailTemplaterLogic)
    const { setEmailEditorRef, onEmailEditorReady, setIsModalOpen, applyTemplate } = useActions(emailTemplaterLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const isMessagingProductEnabled = featureFlags[FEATURE_FLAGS.MESSAGING]

    return (
        <>
            <Form
                className="flex overflow-hidden flex-col flex-1 rounded border"
                logic={emailTemplaterLogic}
                props={logicProps}
                formKey="emailTemplate"
            >
                {EMAIL_TYPE_SUPPORTED_FIELDS[logicProps.type].map((field) => (
                    <LemonField
                        key={field.key}
                        name={field.key}
                        className="gap-1 pl-2 border-b shrink-0"
                        // We will handle the error display ourselves
                        renderError={() => null}
                        showOptional={field.optional}
                    >
                        {({ value, onChange, error }) => (
                            <div className="flex items-center gap-2">
                                <LemonLabel
                                    className={error ? 'text-danger' : ''}
                                    info={field.helpText}
                                    showOptional={field.optional}
                                >
                                    {field.label}
                                </LemonLabel>
                                {field.key === 'from_integration' ? (
                                    <NativeEmailIntegrationChoice value={value} onChange={onChange} />
                                ) : (
                                    <CodeEditorInline
                                        embedded
                                        className="flex-1"
                                        globals={logicProps.variables}
                                        value={value}
                                        onChange={onChange}
                                    />
                                )}
                            </div>
                        )}
                    </LemonField>
                ))}

                {isMessagingProductEnabled && (
                    <div className="flex items-center gap-2 m-2">
                        <LemonLabel>Start from a template (optional)</LemonLabel>
                        <LemonSelect
                            placeholder="Choose template"
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
                            disabledReason={templates.length > 0 ? undefined : 'No templates created yet'}
                        />
                    </div>
                )}

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
                            customJS: isMessagingProductEnabled ? [unsubscribeLinkToolCustomJs] : [],
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

function EmailTemplaterForm({ mode }: { mode: EmailEditorMode }): JSX.Element {
    const { logicProps } = useValues(emailTemplaterLogic)

    switch (logicProps.type) {
        case 'email':
            return <DestinationEmailTemplaterForm mode={mode} />
        case 'native_email_template':
        case 'native_email':
            return <NativeEmailTemplaterForm mode={mode} />
    }
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
            <div className="h-[80vh] flex">
                <div className="flex flex-col flex-1">
                    <div className="shrink-0">
                        <h2>Editing email template</h2>
                    </div>
                    <EmailTemplaterForm mode="full" />
                    <div className="flex gap-2 items-center mt-2">
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
            <div className="flex flex-col flex-1">
                <EmailTemplaterForm mode="preview" />
                <EmailTemplaterModal />
            </div>
        </BindLogic>
    )
}
