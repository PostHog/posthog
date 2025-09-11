import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import EmailEditor from 'react-email-editor'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { CyclotronJobTemplateSuggestionsButton } from 'lib/components/CyclotronJob/CyclotronJobTemplateSuggestions'
import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { urls } from 'scenes/urls'

import { unsubscribeLinkToolCustomJs } from './custom-tools/unsubscribeLinkTool'
import { EmailTemplaterLogicProps, emailTemplaterLogic } from './emailTemplaterLogic'

export type EmailEditorMode = 'full' | 'preview'

/**
 * email: basic email editor with free-text fields, used for configuring email platform realtime destinations
 * native_email: advanced editor with email integration dropdown, and additional email metafields
 * native_email-template: editor for creating reusable templates, with only subject and preheader, and email content fields
 */
export type EmailTemplaterType = 'email' | 'native_email' | 'native_email_template'
type EmailMetaFieldKey = 'from' | 'preheader' | 'to' | 'subject'
type EmailMetaField = {
    key: EmailMetaFieldKey
    label: string
    optional: boolean
    helpText?: string
    isAdvancedField?: boolean
}

const EMAIL_META_FIELDS = {
    FROM: { key: 'from', label: 'From', optional: false },
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
        EMAIL_META_FIELDS.FROM,
        EMAIL_META_FIELDS.TO,
        EMAIL_META_FIELDS.SUBJECT,
        EMAIL_META_FIELDS.PREHEADER,
    ],
    native_email_template: [EMAIL_META_FIELDS.SUBJECT, EMAIL_META_FIELDS.PREHEADER],
}

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
                            <div className="flex gap-2 items-center">
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

function NativeEmailIntegrationChoice({
    onChange,
    value,
}: {
    onChange: (value: any) => void
    value: any
}): JSX.Element {
    const { integrationsLoading, integrations } = useValues(integrationsLogic)
    const integrationsOfKind = integrations?.filter((x) => x.kind === 'email')

    const onChangeIntegration = (integrationId: number): void => {
        if (integrationId === -1) {
            // Open new integration modal
            window.open(urls.messaging('channels'), '_blank')
            return
        }
        const integration = integrationsOfKind?.find((x) => x.id === integrationId)
        onChange({
            integrationId,
            email: integration?.config?.email_address ?? 'default@example.com', // TODO: Remove this default later
            // name: integration?.config?.name, // TODO: Add support for the name?
        })
    }

    if (!integrationsLoading && integrationsOfKind?.length === 0) {
        return (
            <div className="flex gap-2 justify-end items-center">
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
                className="m-1 flex-1"
                type="tertiary"
                placeholder="Choose email sender"
                loading={integrationsLoading}
                options={[
                    {
                        title: 'Email senders',
                        options: (integrationsOfKind || []).map((integration) => ({
                            label: integration.display_name,
                            value: integration.id,
                        })),
                    },
                    {
                        options: [
                            {
                                label: 'Add new email sender',
                                icon: <IconExternal />,
                                value: -1,
                            },
                        ],
                    },
                ]}
                value={value?.integrationId}
                size="small"
                fullWidth
                onChange={onChangeIntegration}
            />
        </>
    )
}

function LiquidSupportedText({
    value,
    onChange,
    globals,
}: {
    value: string
    onChange: (value?: string) => void
    globals: any
}): JSX.Element {
    const { templatingEngine } = useValues(emailTemplaterLogic)
    const { setTemplatingEngine } = useActions(emailTemplaterLogic)

    return (
        <span className="flex grow group relative justify-between">
            <span className="absolute top-0 right-2 z-20 p-px opacity-0 transition-opacity group-hover:opacity-100">
                <CyclotronJobTemplateSuggestionsButton
                    templating={templatingEngine}
                    setTemplatingEngine={setTemplatingEngine}
                    value={value}
                    onOptionSelect={(option) => {
                        onChange?.(`${value || ''}${option.example}`)
                    }}
                />
            </span>
            <CodeEditorInline embedded className="flex-1" globals={globals} value={value} onChange={onChange} />
        </span>
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
                            <div className="flex gap-2 items-center">
                                <LemonLabel
                                    className={error ? 'text-danger' : ''}
                                    info={field.helpText}
                                    showOptional={field.optional}
                                >
                                    {field.label}
                                </LemonLabel>
                                {field.key === 'from' ? (
                                    <NativeEmailIntegrationChoice value={value} onChange={onChange} />
                                ) : field.key === 'to' ? (
                                    /**
                                     * In email inputs, "to" maps to { email: string; name: string; },
                                     * whereas other fields map directly to their string value
                                     */
                                    <LiquidSupportedText
                                        value={value?.email}
                                        onChange={(email) => onChange({ ...value, email })}
                                        globals={logicProps.variables}
                                    />
                                ) : (
                                    <LiquidSupportedText
                                        value={value}
                                        onChange={onChange}
                                        globals={logicProps.variables}
                                    />
                                )}
                            </div>
                        )}
                    </LemonField>
                ))}

                {mode === 'full' ? (
                    <>
                        {isMessagingProductEnabled && (
                            <div className="flex gap-2 items-center px-2 py-1 border-b">
                                <span className="flex-1">Start from a template (optional)</span>
                                <LemonSelect
                                    size="xsmall"
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
                    </>
                ) : (
                    <LemonField name="html" className="flex relative flex-col">
                        {({ value }) => (
                            <>
                                <div
                                    className={clsx(
                                        'flex absolute inset-0 justify-center items-center p-2 opacity-0 transition-opacity hover:opacity-100',
                                        value ? 'opacity-0' : 'opacity-100' // Hide if there is content
                                    )}
                                >
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
