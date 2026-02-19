import 'products/workflows/frontend/TemplateLibrary/MessageTemplatesGrid.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { ChildFunctionProps, Form } from 'kea-forms'
import { useCallback, useEffect, useRef, useState } from 'react'
import EmailEditor, { EditorRef } from 'react-email-editor'

import { IconChevronDown, IconChevronLeft, IconChevronRight, IconExternal } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonModal, LemonSelect, LemonTabs } from '@posthog/lemon-ui'

import { CyclotronJobTemplateSuggestionsButton } from 'lib/components/CyclotronJob/CyclotronJobTemplateSuggestions'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { urls } from 'scenes/urls'

import { MessageTemplateCard } from 'products/workflows/frontend/TemplateLibrary/MessageTemplateCard'

import { unsubscribeLinkToolCustomJs } from './custom-tools/unsubscribeLinkTool'
import { EmailTemplaterLogicProps, emailTemplaterLogic } from './emailTemplaterLogic'

export type EmailEditorMode = 'full' | 'preview'

/**
 * email: basic email editor with free-text fields, used for configuring email platform realtime destinations
 * native_email: advanced editor with email integration dropdown, and additional email metafields
 * native_email-template: editor for creating reusable templates, with only subject and preheader, and email content fields
 */
export type EmailTemplaterType = 'email' | 'native_email' | 'native_email_template'
type EmailMetaFieldKey = 'from' | 'to' | 'replyTo' | 'subject' | 'preheader'
type EmailMetaField = {
    key: EmailMetaFieldKey
    label: string
    optional: boolean
    helpText?: string
    isAdvancedField?: boolean
}

const EMAIL_META_FIELDS = {
    FROM: { key: 'from', label: 'From', optional: false },
    TO: { key: 'to', label: 'To', optional: false },
    REPLY_TO: {
        key: 'replyTo',
        label: 'Reply-To',
        optional: true,
        helpText: 'Optional reply-to email address. You can comma separate multiple reply-to addresses.',
    },
    PREHEADER: {
        key: 'preheader',
        label: 'Preheader',
        optional: true,
        helpText: 'This is the preview text that appears below the subject line in an inbox.',
    },
    SUBJECT: { key: 'subject', label: 'Subject', optional: false },
} as const

const EMAIL_TYPE_SUPPORTED_FIELDS: Record<EmailTemplaterType, EmailMetaField[]> = {
    email: [EMAIL_META_FIELDS.FROM, EMAIL_META_FIELDS.TO, EMAIL_META_FIELDS.SUBJECT],
    native_email: [
        EMAIL_META_FIELDS.FROM,
        EMAIL_META_FIELDS.TO,
        EMAIL_META_FIELDS.REPLY_TO,
        EMAIL_META_FIELDS.SUBJECT,
        EMAIL_META_FIELDS.PREHEADER,
    ],
    native_email_template: [EMAIL_META_FIELDS.SUBJECT, EMAIL_META_FIELDS.PREHEADER],
}

function PlainTextEditor(): JSX.Element {
    const { logicProps, templatingEngine } = useValues(emailTemplaterLogic)
    const { setTemplatingEngine } = useActions(emailTemplaterLogic)

    return (
        <LemonField name="text" className="flex flex-col flex-1">
            {({ value, onChange }: ChildFunctionProps) => (
                <div className="flex flex-col flex-1 relative group">
                    <span className="absolute top-1 right-2 z-20 p-px opacity-0 transition-opacity group-hover:opacity-100">
                        <CyclotronJobTemplateSuggestionsButton
                            templating={templatingEngine}
                            setTemplatingEngine={setTemplatingEngine}
                            value={value}
                            onOptionSelect={(option) => {
                                onChange(`${value || ''}${option.example}`)
                            }}
                        />
                    </span>
                    <CodeEditorResizeable
                        className="flex-1"
                        language={templatingEngine === 'hog' ? 'hogTemplate' : 'liquid'}
                        value={value}
                        onChange={onChange}
                        globals={logicProps.variables}
                        options={{
                            wordWrap: 'on',
                            lineNumbers: 'off',
                            minimap: { enabled: false },
                        }}
                        minHeight="100%"
                        maxHeight="100%"
                        allowManualResize={false}
                    />
                </div>
            )}
        </LemonField>
    )
}

function DestinationEmailTemplaterForm({ mode }: { mode: EmailEditorMode }): JSX.Element {
    const { logicProps, mergeTags, activeContentTab } = useValues(emailTemplaterLogic)
    const { setEmailEditorRef, onEmailEditorReady, setIsModalOpen, setActiveContentTab } =
        useActions(emailTemplaterLogic)

    return (
        <>
            <Form
                {...{ className: 'flex overflow-hidden flex-col flex-1 rounded border' }}
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
                        {({ value, onChange, error }: ChildFunctionProps) => (
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
                    <>
                        <LemonTabs
                            activeKey={activeContentTab}
                            onChange={(key) => setActiveContentTab(key as 'visual' | 'plaintext')}
                            tabs={[
                                { key: 'visual', label: 'Visual' },
                                { key: 'plaintext', label: 'Plain text' },
                            ]}
                            className="px-2 shrink-0 border-b"
                        />
                        <div className="relative flex flex-col flex-1">
                            <div
                                className={clsx(
                                    activeContentTab === 'visual'
                                        ? 'flex flex-col flex-1'
                                        : 'absolute inset-0 -z-10 opacity-0 pointer-events-none'
                                )}
                            >
                                <EmailEditor
                                    ref={(r: EditorRef | null) => setEmailEditorRef(r)}
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
                            </div>
                            {activeContentTab === 'plaintext' && <PlainTextEditor />}
                        </div>
                    </>
                ) : (
                    <LemonField name="html" className="flex relative flex-col">
                        {({ value }: ChildFunctionProps) => (
                            <>
                                <div className="flex absolute inset-0 justify-center items-end p-2 opacity-0 transition-opacity hover:opacity-100">
                                    <div className="absolute inset-0 opacity-50 bg-surface-primary" />
                                    <LemonButton type="primary" size="small" onClick={() => setIsModalOpen(true)}>
                                        Click to modify content
                                    </LemonButton>
                                </div>

                                <iframe srcDoc={value} sandbox="" className="flex-1" />
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
            window.open(urls.workflows('channels'), '_blank')
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
                    to={urls.workflows('channels')}
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

    const templating = templatingEngine ?? 'hog'

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
            <CodeEditorInline
                embedded
                className="flex-1"
                globals={globals}
                value={value}
                language={templating === 'hog' ? 'hogTemplate' : 'liquid'}
                onChange={onChange}
            />
        </span>
    )
}

const CARD_WIDTH = 192 // w-48
const CARD_GAP = 12 // gap-3

function TemplateSlider({
    templates,
    onSelect,
    onSaveAsTemplate,
}: {
    templates: any[]
    onSelect: (template: any) => void
    onSaveAsTemplate?: () => void
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const [page, setPage] = useState(0)
    const [pageSize, setPageSize] = useState(5)
    const containerRef = useRef<HTMLDivElement>(null)

    const updatePageSize = useCallback(() => {
        if (containerRef.current) {
            const width = containerRef.current.offsetWidth
            const count = Math.max(1, Math.floor((width + CARD_GAP) / (CARD_WIDTH + CARD_GAP)))
            setPageSize(count)
        }
    }, [])

    useEffect(() => {
        if (!expanded) {
            return
        }
        updatePageSize()
        const observer = new ResizeObserver(updatePageSize)
        if (containerRef.current) {
            observer.observe(containerRef.current)
        }
        return () => observer.disconnect()
    }, [expanded, updatePageSize])

    const totalPages = Math.ceil(templates.length / pageSize)
    const clampedPage = Math.min(page, totalPages - 1)
    const visibleTemplates = templates.slice(clampedPage * pageSize, (clampedPage + 1) * pageSize)

    return (
        <div className="border-b">
            <div
                className="flex gap-2 items-center px-2 py-1 cursor-pointer select-none"
                onClick={() => setExpanded(!expanded)}
            >
                <IconChevronDown className={clsx('w-4 h-4 transition-transform', !expanded && '-rotate-90')} />
                <span className="flex-1 text-sm text-secondary">Start from a template (optional)</span>
                {onSaveAsTemplate && (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={(e) => {
                            e.stopPropagation()
                            onSaveAsTemplate()
                        }}
                    >
                        Save as new template
                    </LemonButton>
                )}
            </div>
            {expanded && (
                <div ref={containerRef} className="flex items-center gap-1 px-1 pb-2">
                    <LemonButton
                        size="small"
                        icon={<IconChevronLeft />}
                        disabled={clampedPage === 0}
                        onClick={() => setPage(clampedPage - 1)}
                    />
                    <div className="flex gap-3 flex-1 overflow-hidden" key={clampedPage}>
                        {visibleTemplates.map((template, index) => (
                            <div
                                key={template.id}
                                className="shrink-0 w-48 h-56 MessageTemplateSlider__SlideIn--animate"
                                style={{ animationDelay: `${index * 50}ms` }}
                            >
                                <MessageTemplateCard
                                    template={template}
                                    index={clampedPage * pageSize + index}
                                    onClick={() => onSelect(template)}
                                />
                            </div>
                        ))}
                    </div>
                    <LemonButton
                        size="small"
                        icon={<IconChevronRight />}
                        disabled={clampedPage >= totalPages - 1}
                        onClick={() => setPage(clampedPage + 1)}
                    />
                </div>
            )}
        </div>
    )
}

function NativeEmailTemplaterForm({
    mode,
    onSaveAsTemplate,
}: {
    mode: EmailEditorMode
    onSaveAsTemplate?: () => void
}): JSX.Element {
    const { unlayerEditorProjectId, logicProps, templates, mergeTags, activeContentTab } =
        useValues(emailTemplaterLogic)
    const { setEmailEditorRef, onEmailEditorReady, setIsModalOpen, applyTemplate, setActiveContentTab } =
        useActions(emailTemplaterLogic)

    const [previewTemplate, setPreviewTemplate] = useState<(typeof templates)[0] | null>(null)

    return (
        <>
            <Form
                {...{ className: 'flex overflow-hidden flex-col flex-1 rounded border' }}
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
                        {({ value, onChange, error }: ChildFunctionProps) => (
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
                        {templates.length > 0 && (
                            <TemplateSlider
                                templates={templates}
                                onSelect={applyTemplate}
                                onSaveAsTemplate={onSaveAsTemplate}
                            />
                        )}
                        <LemonTabs
                            activeKey={activeContentTab}
                            onChange={(key) => setActiveContentTab(key as 'visual' | 'plaintext')}
                            tabs={[
                                { key: 'visual', label: 'Visual' },
                                { key: 'plaintext', label: 'Plain text' },
                            ]}
                            className="px-2 shrink-0 border-b"
                        />
                        <div className="relative flex flex-col flex-1">
                            <div
                                className={clsx(
                                    activeContentTab === 'visual'
                                        ? 'flex flex-col flex-1'
                                        : 'absolute inset-0 -z-10 opacity-0 pointer-events-none'
                                )}
                            >
                                <EmailEditor
                                    ref={(r: EditorRef | null) => setEmailEditorRef(r)}
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
                                        customJS: [unsubscribeLinkToolCustomJs],
                                        fonts: unlayerEditorProjectId
                                            ? {
                                                  showDefaultFonts: true,
                                                  customFonts: [
                                                      {
                                                          label: 'Ubuntu',
                                                          value: "'Ubuntu',sans-serif",
                                                          url: 'https://fonts.googleapis.com/css2?family=Ubuntu:ital,wght@0,300;0,400;0,500;0,700;1,300;1,400;1,500;1,700&display=swap',
                                                          weights: [
                                                              { label: 'Light', value: 300 },
                                                              { label: 'Regular', value: 400 },
                                                              { label: 'Medium', value: 500 },
                                                              { label: 'Bold', value: 700 },
                                                          ],
                                                      },
                                                  ],
                                              }
                                            : undefined,
                                    }}
                                />
                            </div>
                            {activeContentTab === 'plaintext' && <PlainTextEditor />}
                        </div>
                        <LemonModal
                            isOpen={!!previewTemplate}
                            onClose={() => setPreviewTemplate(null)}
                            title={`Preview: ${previewTemplate?.name}`}
                            width="90vw"
                        >
                            <div className="h-[80vh] overflow-auto">
                                <iframe
                                    srcDoc={previewTemplate?.content.email.html}
                                    sandbox=""
                                    className="w-full h-full border-0"
                                />
                            </div>
                        </LemonModal>
                    </>
                ) : (
                    <LemonField name="html" className="flex relative flex-col">
                        {({ value }: ChildFunctionProps) => (
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

                                <iframe srcDoc={value} sandbox="" className="flex-1" />
                            </>
                        )}
                    </LemonField>
                )}
            </Form>
        </>
    )
}

function EmailTemplaterForm({
    mode,
    onSaveAsTemplate,
}: {
    mode: EmailEditorMode
    onSaveAsTemplate?: () => void
}): JSX.Element {
    const { logicProps } = useValues(emailTemplaterLogic)

    switch (logicProps.type) {
        case 'email':
            return <DestinationEmailTemplaterForm mode={mode} />
        case 'native_email_template':
        case 'native_email':
            return <NativeEmailTemplaterForm mode={mode} onSaveAsTemplate={onSaveAsTemplate} />
    }
}

function SaveTemplateModal({
    isOpen,
    onClose,
    onSave,
}: {
    isOpen: boolean
    onClose: () => void
    onSave: (name: string, description: string) => void
}): JSX.Element {
    const [templateName, setTemplateName] = useState('')
    const [templateDescription, setTemplateDescription] = useState('')

    const handleClose = (): void => {
        setTemplateName('')
        setTemplateDescription('')
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            title="Save as template"
            description="Create a reusable template from this email"
            footer={
                <>
                    <LemonButton onClick={handleClose}>Cancel</LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            if (templateName) {
                                onSave(templateName, templateDescription)
                                setTemplateName('')
                                setTemplateDescription('')
                            }
                        }}
                        disabledReason={!templateName ? 'Please enter a template name' : undefined}
                    >
                        Save template
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                <div className="flex flex-col gap-1">
                    <LemonLabel>Template name</LemonLabel>
                    <LemonInput
                        placeholder="My Email Template"
                        value={templateName}
                        onChange={setTemplateName}
                        autoFocus
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel showOptional>Description</LemonLabel>
                    <LemonTextArea
                        placeholder="Describe when to use this template..."
                        value={templateDescription}
                        onChange={setTemplateDescription}
                        rows={3}
                    />
                </div>
            </div>
        </LemonModal>
    )
}

function EmailTemplaterModal(): JSX.Element {
    const { isModalOpen, isEmailEditorReady, emailTemplateChanged, isSaveTemplateModalOpen } =
        useValues(emailTemplaterLogic)
    const { closeWithConfirmation, submitEmailTemplate, saveAsTemplate, setIsSaveTemplateModalOpen } =
        useActions(emailTemplaterLogic)

    return (
        <>
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
                        <EmailTemplaterForm mode="full" onSaveAsTemplate={() => setIsSaveTemplateModalOpen(true)} />
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
            <SaveTemplateModal
                isOpen={isSaveTemplateModalOpen}
                onClose={() => setIsSaveTemplateModalOpen(false)}
                onSave={(name, description) => saveAsTemplate(name, description)}
            />
        </>
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
