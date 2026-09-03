import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { ChildFunctionProps, Form } from 'kea-forms'
import { ReactNode, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import EmailEditor, { EditorRef } from 'react-email-editor'

import { IconCollapse, IconExpand, IconExternal, IconPlus, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonCard,
    LemonInputSelect,
    LemonLabel,
    LemonModal,
    LemonSegmentedButton,
    LemonSelect,
} from '@posthog/lemon-ui'

import { CyclotronJobTemplateSuggestionsButton } from 'lib/components/CyclotronJob/CyclotronJobTemplateSuggestions'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { sceneAgentPanelLogic } from 'scenes/max/sceneAgentPanelLogic'
import { urls } from 'scenes/urls'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'

import 'products/workflows/frontend/TemplateLibrary/MessageTemplatesGrid.scss'
import { MessageTemplateCard } from 'products/workflows/frontend/TemplateLibrary/MessageTemplateCard'

import { collapseToolsPanelCustomJs } from './custom-tools/collapseToolsPanel'
import { unsubscribeLinkToolCustomJs } from './custom-tools/unsubscribeLinkTool'
import { EMAIL_TYPE_SUPPORTED_FIELDS, EmailTemplaterLogicProps, emailTemplaterLogic } from './emailTemplaterLogic'
import { EmailFieldErrors, EmailTemplateFrom, MAX_WORKFLOW_EMAIL_SENDERS } from './types'

export type EmailEditorMode = 'full' | 'preview'

// Maps a templater field key onto its validation message slot. Only the sender, recipient, and
// subject rows have their own message; body content is reported separately near the editor.
function fieldErrorFor(fieldKey: string, fieldErrors?: EmailFieldErrors): string | undefined {
    if (fieldKey === 'from' || fieldKey === 'to' || fieldKey === 'subject') {
        return fieldErrors?.[fieldKey]
    }
    return undefined
}

function FieldErrorMessage({ error }: { error?: string }): JSX.Element | null {
    if (!error) {
        return null
    }
    return <div className="pb-1 pl-2 text-xs text-danger">{error}</div>
}

function AddAdvancedFieldButtons(): JSX.Element | null {
    const { hiddenAdvancedFields } = useValues(emailTemplaterLogic)
    const { revealAdvancedField } = useActions(emailTemplaterLogic)

    if (hiddenAdvancedFields.length === 0) {
        return null
    }

    return (
        <div className="flex gap-1 px-2 py-1 border-b shrink-0">
            {hiddenAdvancedFields.map((field) => (
                <LemonButton
                    key={field.key}
                    size="xsmall"
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={() => revealAdvancedField(field.key)}
                >
                    {field.label}
                </LemonButton>
            ))}
        </div>
    )
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

function DestinationEmailTemplaterForm({
    mode,
    fieldsHidden,
}: {
    mode: EmailEditorMode
    fieldsHidden?: boolean
}): JSX.Element {
    const { logicProps, mergeTags, activeContentTab, emailTemplate } = useValues(emailTemplaterLogic)
    const { setEmailEditorRef, onEmailEditorReady } = useActions(emailTemplaterLogic)

    return (
        <>
            <Form
                {...{ className: 'flex overflow-hidden flex-col flex-1 rounded border' }}
                logic={emailTemplaterLogic}
                props={logicProps}
                formKey="emailTemplate"
            >
                <div className={fieldsHidden ? 'h-0 overflow-hidden' : ''}>
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
                </div>

                {mode === 'full' ? (
                    <>
                        <div className="relative flex flex-col flex-1">
                            <div
                                className={clsx(
                                    activeContentTab === 'visual'
                                        ? 'flex flex-col flex-1'
                                        : // invisible releases the hidden editor's raster backing while
                                          // visibility (unlike display:none) preserves its layout state
                                          'absolute inset-0 -z-10 opacity-0 pointer-events-none invisible'
                                )}
                            >
                                <EmailEditor
                                    ref={(r: EditorRef | null) => setEmailEditorRef(r)}
                                    onReady={() => onEmailEditorReady()}
                                    minHeight={20}
                                    options={{
                                        mergeTags,
                                        displayMode: 'email',
                                        appearance: {
                                            actionBar: {
                                                placement: 'bottom',
                                            },
                                            panels: {
                                                tools: {
                                                    dock: 'right',
                                                    collapsible: true,
                                                },
                                            },
                                        },
                                        features: {
                                            preview: true,
                                            imageEditor: true,
                                            stockImages: false,
                                            // Unlayer's AI features (Magic Image, smart text, the AI
                                            // assistant) default to on; they're third-party AI consuming
                                            // paid credits from our Unlayer workspace, so keep them all off.
                                            ai: false,
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
                                <div
                                    className={clsx(
                                        'flex absolute inset-0 justify-center items-end p-2 transition-opacity',
                                        // Persistent start buttons while empty; hover-reveal once there is content
                                        value ? 'opacity-0 hover:opacity-100' : 'opacity-100'
                                    )}
                                >
                                    <div className="absolute inset-0 opacity-50 bg-surface-primary" />
                                    {/* A plain-text-only email has no html, so content is judged on every shape */}
                                    <EmailPreviewOverlayButtons
                                        hasContent={!!value || !!emailTemplate.text || !!emailTemplate.design}
                                    />
                                </div>

                                <iframe srcDoc={value} sandbox="" title="Email template preview" className="flex-1" />
                            </>
                        )}
                    </LemonField>
                )}
            </Form>
        </>
    )
}

export function NativeEmailIntegrationChoice({
    label,
    onChange,
    value,
}: {
    /** Rendered inside the sender row so it aligns with the select rather than spanning the override rows. */
    label: ReactNode
    onChange: (value: EmailTemplateFrom) => void
    value?: EmailTemplateFrom
}): JSX.Element {
    const { integrationsLoading, integrations } = useValues(integrationsLogic)
    const { logicProps } = useValues(emailTemplaterLogic)
    const senderRotationEnabled = useFeatureFlag('WORKFLOWS_EMAIL_SENDER_ROTATION')
    const integrationsOfKind = integrations?.filter((x) => x.kind === 'email')
    const selectedIntegrationIds = value?.integrationIds?.length
        ? value.integrationIds
        : value?.integrationId
          ? [value.integrationId]
          : []

    // Presence of the override keys is what reveals the inputs, so a saved override is
    // visible again on reopen without any separate reveal state.
    const overridesVisible = value?.email !== undefined || value?.name !== undefined

    const onChangeIntegration = (integrationId: number): void => {
        if (integrationId === -1) {
            window.open(urls.workflows('channels'), '_blank')
            return
        }
        onChange({ ...value, integrationId, integrationIds: undefined })
    }

    const onChangeIntegrations = (integrationIds: number[]): void => {
        if (integrationIds.length > MAX_WORKFLOW_EMAIL_SENDERS) {
            return
        }
        onChange({
            ...value,
            integrationId: integrationIds[0],
            integrationIds: integrationIds.length > 1 ? integrationIds : undefined,
        })
    }

    if (!integrationsLoading && integrationsOfKind?.length === 0) {
        return (
            <div className="flex gap-2 justify-between items-center">
                {label}
                <div className="flex gap-2 items-center">
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
            </div>
        )
    }

    return (
        <div className="flex flex-col">
            <div className="flex gap-2 items-center">
                {label}
                {senderRotationEnabled ? (
                    <div className="flex flex-col flex-1">
                        <LemonInputSelect<number>
                            className="m-1 flex-1"
                            mode="multiple"
                            placeholder="Choose email senders"
                            loading={integrationsLoading}
                            options={(integrationsOfKind || []).map((integration) => ({
                                key: String(integration.id),
                                label: integration.display_name,
                                value: integration.id,
                            }))}
                            value={selectedIntegrationIds}
                            size="small"
                            fullWidth
                            autoWidth={false}
                            onChange={onChangeIntegrations}
                            data-attr="workflow-email-sender-select"
                            action={{
                                children: 'Add new email sender',
                                icon: <IconExternal />,
                                onClick: () => window.open(urls.workflows('channels'), '_blank'),
                            }}
                        />
                        <span className="px-2 pb-1 text-xs text-muted">
                            Choose up to {MAX_WORKFLOW_EMAIL_SENDERS} senders. Each workflow run uses one sender from
                            this list.
                        </span>
                    </div>
                ) : (
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
                        data-attr="workflow-email-sender-select"
                    />
                )}
                {!overridesVisible && (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconPlus />}
                        className="mr-2 shrink-0"
                        data-attr="email-from-custom-sender"
                        onClick={() => onChange({ ...value, email: '', name: '' })}
                        tooltip="Set a custom sender address or name, with template support"
                    >
                        Custom sender
                    </LemonButton>
                )}
            </div>
            {overridesVisible && (
                <>
                    <div className="flex gap-2 items-center border-t">
                        <LemonLabel
                            className="min-w-30 shrink-0"
                            info="The address to send from. Templates are supported, so the address can come from the triggering event. It must be on every selected sender's verified domain. Leave empty to use the sender's address."
                        >
                            Custom address
                        </LemonLabel>
                        <LiquidSupportedText
                            value={value?.email ?? ''}
                            onChange={(email) => onChange({ ...value, email })}
                            globals={logicProps.variables}
                        />
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconX />}
                            className="mr-2"
                            data-attr="email-from-custom-sender-remove"
                            onClick={() => onChange({ ...value, email: undefined, name: undefined })}
                            tooltip="Remove custom sender"
                        />
                    </div>
                    <div className="flex gap-2 items-center border-t">
                        <LemonLabel
                            className="min-w-30 shrink-0"
                            info="The sender name shown in the recipient's inbox. Templates are supported. Leave empty to use the sender's name."
                        >
                            Custom name
                        </LemonLabel>
                        <LiquidSupportedText
                            value={value?.name ?? ''}
                            onChange={(name) => onChange({ ...value, name })}
                            globals={logicProps.variables}
                        />
                    </div>
                </>
            )}
        </div>
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

export function TemplatePickerModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    const { templates } = useValues(emailTemplaterLogic)
    const { applyTemplate } = useActions(emailTemplaterLogic)

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="Choose a starting point" width={880}>
            <div className="flex flex-wrap gap-3">
                <LemonCard
                    className="w-48 h-56 flex flex-col gap-2 items-center justify-center cursor-pointer"
                    onClick={onClose}
                    data-attr="template-picker-blank"
                >
                    <IconPlus className="text-2xl" />
                    <span>Blank template</span>
                </LemonCard>
                {templates.map((template, index) => (
                    <div key={template.id} className="w-48 h-56">
                        <MessageTemplateCard
                            template={template}
                            index={index}
                            onClick={() => {
                                applyTemplate(template)
                                onClose()
                            }}
                        />
                    </div>
                ))}
            </div>
        </LemonModal>
    )
}

function NativeEmailTemplaterForm({
    mode,
    fieldsHidden,
}: {
    mode: EmailEditorMode
    fieldsHidden?: boolean
}): JSX.Element {
    const { unlayerEditorProjectId, logicProps, templates, mergeTags, activeContentTab, visibleFields, emailTemplate } =
        useValues(emailTemplaterLogic)
    const { setEmailEditorRef, onEmailEditorReady, setActiveContentTab, hideAdvancedField, revealAdvancedField } =
        useActions(emailTemplaterLogic)
    // With the AI panel integration on, chat sits beside the editor and width is scarce, so the
    // Unlayer tools panel starts collapsed to give the canvas room.
    const { sceneIntegrationEnabled } = useValues(sceneAgentPanelLogic)

    // The template editor has only subject + preheader, so they share one row with the
    // visual/plain-text switch to keep vertical space for the canvas.
    const compactHeader = logicProps.type === 'native_email_template' && mode === 'full'
    const preheaderVisible = visibleFields.some((field) => field.key === 'preheader')
    // Preheaders see almost no use, so don't advertise the field unless this team already uses it.
    const offerPreheader = templates.some((template) => !!template.content?.email?.preheader)

    return (
        <>
            <Form
                {...{ className: 'flex overflow-hidden flex-col flex-1 rounded border' }}
                logic={emailTemplaterLogic}
                props={logicProps}
                formKey="emailTemplate"
            >
                <div className={fieldsHidden ? 'h-0 overflow-hidden' : ''}>
                    {compactHeader ? (
                        <div className="flex gap-2 items-center pl-2 pr-1 py-0.5 border-b shrink-0">
                            <LemonField name="subject" className="flex-2 min-w-40" renderError={() => null}>
                                {({ value, onChange, error }: ChildFunctionProps) => (
                                    <div className="flex gap-2 items-center flex-1">
                                        <LemonLabel className={error ? 'text-danger' : ''}>Subject</LemonLabel>
                                        <LiquidSupportedText
                                            value={value}
                                            onChange={onChange}
                                            globals={logicProps.variables}
                                        />
                                    </div>
                                )}
                            </LemonField>
                            {preheaderVisible ? (
                                <LemonField name="preheader" className="flex-1 min-w-40" renderError={() => null}>
                                    {({ value, onChange }: ChildFunctionProps) => (
                                        <div className="flex gap-2 items-center flex-1">
                                            <LemonLabel info="This is the preview text that appears below the subject line in an inbox.">
                                                Preheader
                                            </LemonLabel>
                                            <LiquidSupportedText
                                                value={value}
                                                onChange={onChange}
                                                globals={logicProps.variables}
                                            />
                                            <LemonButton
                                                size="xsmall"
                                                type="tertiary"
                                                icon={<IconX />}
                                                onClick={() => {
                                                    onChange('')
                                                    hideAdvancedField('preheader')
                                                }}
                                                tooltip="Remove field"
                                            />
                                        </div>
                                    )}
                                </LemonField>
                            ) : offerPreheader ? (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    icon={<IconPlus />}
                                    onClick={() => revealAdvancedField('preheader')}
                                >
                                    Preheader
                                </LemonButton>
                            ) : null}
                            <LemonSegmentedButton
                                size="small"
                                className="ml-2 shrink-0"
                                value={activeContentTab}
                                onChange={(tab) => setActiveContentTab(tab as 'visual' | 'plaintext')}
                                options={[
                                    { value: 'visual', label: 'Visual' },
                                    { value: 'plaintext', label: 'Plain text' },
                                ]}
                            />
                        </div>
                    ) : (
                        visibleFields.map((field) => {
                            const fieldError = fieldErrorFor(field.key, logicProps.fieldErrors)
                            return (
                                <div key={field.key} className="border-b shrink-0">
                                    <LemonField
                                        name={field.key}
                                        className="gap-1 pl-2"
                                        // We will handle the error display ourselves
                                        renderError={() => null}
                                        showOptional={field.optional}
                                    >
                                        {({ value, onChange }: ChildFunctionProps) => {
                                            const label = (
                                                <LemonLabel
                                                    className={fieldError ? 'text-danger' : ''}
                                                    info={field.helpText}
                                                    showOptional={field.optional}
                                                >
                                                    {field.label}
                                                </LemonLabel>
                                            )
                                            return field.key === 'from' ? (
                                                <NativeEmailIntegrationChoice
                                                    label={label}
                                                    value={value}
                                                    onChange={onChange}
                                                />
                                            ) : (
                                                <div className="flex gap-2 items-center">
                                                    {label}
                                                    {field.key === 'to' ? (
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
                                                    {field.isAdvancedField && (
                                                        <LemonButton
                                                            size="xsmall"
                                                            type="tertiary"
                                                            icon={<IconX />}
                                                            className="mr-2"
                                                            onClick={() => {
                                                                onChange('')
                                                                hideAdvancedField(field.key)
                                                            }}
                                                            tooltip="Remove field"
                                                        />
                                                    )}
                                                </div>
                                            )
                                        }}
                                    </LemonField>
                                    <FieldErrorMessage error={fieldError} />
                                </div>
                            )
                        })
                    )}

                    {!compactHeader && <AddAdvancedFieldButtons />}
                </div>

                {mode === 'full' ? (
                    <>
                        <div className="relative flex flex-col flex-1">
                            <div
                                className={clsx(
                                    activeContentTab === 'visual'
                                        ? 'flex flex-col flex-1'
                                        : // invisible releases the hidden editor's raster backing while
                                          // visibility (unlike display:none) preserves its layout state
                                          'absolute inset-0 -z-10 opacity-0 pointer-events-none invisible'
                                )}
                            >
                                <EmailEditor
                                    ref={(r: EditorRef | null) => setEmailEditorRef(r)}
                                    onReady={() => onEmailEditorReady()}
                                    minHeight={20}
                                    options={{
                                        mergeTags,
                                        displayMode: 'email',
                                        appearance: {
                                            actionBar: {
                                                placement: 'bottom',
                                            },
                                            panels: {
                                                tools: {
                                                    dock: 'right',
                                                    collapsible: true,
                                                },
                                            },
                                        },
                                        features: {
                                            preview: true,
                                            imageEditor: true,
                                            stockImages: false,
                                            // Unlayer's AI features (Magic Image, smart text, the AI
                                            // assistant) default to on; they're third-party AI consuming
                                            // paid credits from our Unlayer workspace, so keep them all off.
                                            ai: false,
                                        },
                                        projectId: unlayerEditorProjectId,
                                        customJS: sceneIntegrationEnabled
                                            ? [unsubscribeLinkToolCustomJs, collapseToolsPanelCustomJs]
                                            : [unsubscribeLinkToolCustomJs],
                                        fonts: unlayerEditorProjectId
                                            ? {
                                                  showDefaultFonts: true,
                                                  customFonts: [
                                                      {
                                                          label: 'Ubuntu',
                                                          value: "'Ubuntu',Tahoma,Verdana,Segoe,sans-serif",
                                                          url: 'https://fonts.googleapis.com/css?family=Ubuntu:300,400,500,700',
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
                    </>
                ) : (
                    <LemonField name="html" className="flex relative flex-col">
                        {({ value }: ChildFunctionProps) => (
                            <>
                                <div
                                    className={clsx(
                                        'flex absolute inset-0 justify-center items-center p-2 transition-opacity',
                                        // Persistent start buttons while empty; hover-reveal once there is content
                                        value ? 'opacity-0 hover:opacity-100' : 'opacity-100'
                                    )}
                                >
                                    <div className="absolute inset-0 opacity-50 bg-surface-primary" />
                                    {/* A plain-text-only email has no html, so content is judged on every shape */}
                                    <EmailPreviewOverlayButtons
                                        hasContent={!!value || !!emailTemplate.text || !!emailTemplate.design}
                                    />
                                </div>

                                <iframe srcDoc={value} sandbox="" title="Email template preview" className="flex-1" />
                            </>
                        )}
                    </LemonField>
                )}
                {/* Rendered in both modes so the message stays visible while the body is edited in
                    the full editor, not just in the preview */}
                <FieldErrorMessage error={logicProps.fieldErrors?.body} />
            </Form>
        </>
    )
}

function EmailPreviewOverlayButtons({ hasContent }: { hasContent: boolean }): JSX.Element {
    const { templates } = useValues(emailTemplaterLogic)
    const { setIsModalOpen, setIsTemplatePickerOpen } = useActions(emailTemplaterLogic)

    if (hasContent) {
        return (
            <LemonButton type="primary" size="small" onClick={() => setIsModalOpen(true)}>
                Click to modify content
            </LemonButton>
        )
    }

    return (
        <div className="flex gap-2 z-10">
            <LemonButton type="primary" size="small" onClick={() => setIsModalOpen(true)}>
                Start blank
            </LemonButton>
            {templates.length > 0 && (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => {
                        setIsModalOpen(true)
                        setIsTemplatePickerOpen(true)
                    }}
                >
                    Start from template
                </LemonButton>
            )}
        </div>
    )
}

function EmailTemplaterForm({ mode, fieldsHidden }: { mode: EmailEditorMode; fieldsHidden?: boolean }): JSX.Element {
    const { logicProps } = useValues(emailTemplaterLogic)

    switch (logicProps.type) {
        case 'email':
            return <DestinationEmailTemplaterForm mode={mode} fieldsHidden={fieldsHidden} />
        case 'native_email_template':
        case 'native_email':
            return <NativeEmailTemplaterForm mode={mode} fieldsHidden={fieldsHidden} />
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

function EmailTemplaterEditorPanel({
    liveChanges,
    saveIndicator,
    onClose,
}: {
    liveChanges?: boolean
    saveIndicator?: ReactNode
    // The takeover has no LemonModal chrome, so it asks for an explicit close button here.
    onClose?: () => void
}): JSX.Element {
    const { isModalOpen, isEmailEditorReady, activeContentTab } = useValues(emailTemplaterLogic)
    const { closeWithConfirmation, submitEmailTemplate, setIsSaveTemplateModalOpen, setActiveContentTab } =
        useActions(emailTemplaterLogic)
    // Fields start collapsed: in embedded contexts they duplicate the surrounding form.
    const [fieldsHidden, setFieldsHidden] = useState(true)

    useEffect(() => {
        if (!isModalOpen) {
            setFieldsHidden(true)
        }
    }, [isModalOpen])

    return (
        <div className="flex-1 min-h-0 flex flex-col gap-2 p-4">
            {/* Without onClose the modal renders its own close button at top-3 right-4; the
                padding keeps our controls clear of it. */}
            <div className={clsx('flex items-center gap-2 shrink-0', !onClose && 'pr-10')}>
                <h2 className="flex-1 min-w-0 truncate my-0">Editing email template</h2>
                {saveIndicator}
                {/* The toggle label changes width; keeping it left of the right-anchored
                    tabs means the tabs never shift when it flips */}
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={fieldsHidden ? <IconExpand /> : <IconCollapse />}
                    onClick={() => setFieldsHidden(!fieldsHidden)}
                >
                    {fieldsHidden ? 'Show fields' : 'Hide fields'}
                </LemonButton>
                <LemonSegmentedButton
                    size="small"
                    value={activeContentTab}
                    onChange={(tab) => setActiveContentTab(tab as 'visual' | 'plaintext')}
                    options={[
                        { value: 'visual', label: 'Visual' },
                        { value: 'plaintext', label: 'Plain text' },
                    ]}
                />
                {onClose && (
                    <LemonButton size="small" icon={<IconX />} onClick={onClose} tooltip="Close" aria-label="Close" />
                )}
            </div>
            <EmailTemplaterForm mode="full" fieldsHidden={fieldsHidden} />
            <div className="flex gap-2 items-center shrink-0">
                <LemonButton type="secondary" onClick={() => setIsSaveTemplateModalOpen(true)}>
                    Save as new template
                </LemonButton>
                <div className="flex-1" />
                {liveChanges ? (
                    // Edits propagate live and the host persists them, so the only
                    // action left is leaving the editor.
                    <LemonButton type="primary" onClick={() => closeWithConfirmation()}>
                        Done
                    </LemonButton>
                ) : (
                    <>
                        <LemonButton onClick={() => closeWithConfirmation()}>Discard changes</LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => submitEmailTemplate()}
                            disabledReason={isEmailEditorReady ? undefined : 'Loading email editor...'}
                        >
                            Save
                        </LemonButton>
                    </>
                )}
            </div>
        </div>
    )
}

function EmailTemplaterTakeover({
    liveChanges,
    saveIndicator,
    host,
}: {
    liveChanges?: boolean
    saveIndicator?: ReactNode
    host: HTMLElement
}): JSX.Element | null {
    const { isModalOpen } = useValues(emailTemplaterLogic)
    const { closeWithConfirmation } = useActions(emailTemplaterLogic)
    const { setSceneTakeoverActive } = useActions(sceneLayoutLogic)

    // The host div is always mounted (and would cover the scene even when empty), so its
    // visibility follows our open state.
    useEffect(() => {
        setSceneTakeoverActive(isModalOpen)
        return () => setSceneTakeoverActive(false)
    }, [isModalOpen, setSceneTakeoverActive])

    // LemonModal handled Escape and focus for the modal variant; the takeover binds its own.
    // Focus moves into the editor on open (keyboard users would otherwise still be on the
    // now-covered scene controls) and returns to the opener on close. No focus trap: the AI
    // side panel next to the editor must stay reachable.
    useEffect(() => {
        if (!isModalOpen) {
            return
        }
        const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
        host.focus()
        const onKeyDown = (e: KeyboardEvent): void => {
            if (e.key === 'Escape') {
                closeWithConfirmation()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => {
            window.removeEventListener('keydown', onKeyDown)
            if (opener && document.contains(opener)) {
                opener.focus()
            }
        }
    }, [isModalOpen, closeWithConfirmation, host])

    if (!isModalOpen) {
        // Mount the editor fresh on every open: re-parenting or hiding a mounted Unlayer iframe
        // reloads it anyway, so there is nothing worth keeping alive while closed.
        return null
    }

    return createPortal(
        <EmailTemplaterEditorPanel
            liveChanges={liveChanges}
            saveIndicator={saveIndicator}
            onClose={() => closeWithConfirmation()}
        />,
        host
    )
}

function EmailTemplaterModal({
    liveChanges,
    saveIndicator,
}: {
    liveChanges?: boolean
    saveIndicator?: ReactNode
}): JSX.Element {
    const { isModalOpen, emailTemplateChanged, isSaveTemplateModalOpen, isTemplatePickerOpen } =
        useValues(emailTemplaterLogic)
    const { closeWithConfirmation, saveAsTemplate, setIsSaveTemplateModalOpen, setIsTemplatePickerOpen } =
        useActions(emailTemplaterLogic)
    const { sceneTakeoverElement } = useValues(sceneLayoutLogic)

    return (
        <>
            {sceneTakeoverElement ? (
                // Fill the main well while the navigation and the AI side panel stay usable
                // beside the editor. A fullscreen LemonModal buries both under its overlay.
                <EmailTemplaterTakeover
                    liveChanges={liveChanges}
                    saveIndicator={saveIndicator}
                    host={sceneTakeoverElement}
                />
            ) : (
                // No takeover host registered (minimal/zen layouts): keep the fullscreen modal.
                <LemonModal
                    isOpen={isModalOpen}
                    fullScreen
                    simple
                    title=""
                    onClose={() => closeWithConfirmation()}
                    hasUnsavedInput={liveChanges ? false : emailTemplateChanged}
                >
                    {/* simple puts us directly in the modal's flex column, so the panel's flex-1
                        fills the screen; a percentage height would collapse inside the default
                        non-flex content wrapper. */}
                    <EmailTemplaterEditorPanel liveChanges={liveChanges} saveIndicator={saveIndicator} />
                </LemonModal>
            )}
            <TemplatePickerModal isOpen={isTemplatePickerOpen} onClose={() => setIsTemplatePickerOpen(false)} />
            <SaveTemplateModal
                isOpen={isSaveTemplateModalOpen}
                onClose={() => setIsSaveTemplateModalOpen(false)}
                onSave={(name, description) => saveAsTemplate(name, description)}
            />
        </>
    )
}

function EmailTemplaterInline(): JSX.Element {
    const { isSaveTemplateModalOpen } = useValues(emailTemplaterLogic)
    const { saveAsTemplate, setIsSaveTemplateModalOpen } = useActions(emailTemplaterLogic)

    return (
        <>
            <EmailTemplaterForm mode="full" />
            <SaveTemplateModal
                isOpen={isSaveTemplateModalOpen}
                onClose={() => setIsSaveTemplateModalOpen(false)}
                onSave={(name, description) => saveAsTemplate(name, description)}
            />
        </>
    )
}

export function EmailTemplater({
    saveIndicator,
    ...props
}: EmailTemplaterLogicProps & {
    // Presentation-only slot rendered in the modal header: hosts using liveChanges surface their
    // own save state here (the workflow builder's auto-save indicator). Kept out of the logic
    // props so a fresh JSX element per render doesn't churn propsChanged.
    saveIndicator?: ReactNode
}): JSX.Element {
    return (
        <BindLogic logic={emailTemplaterLogic} props={props}>
            <div className="flex flex-col flex-1">
                {props.layout === 'inline' ? (
                    <EmailTemplaterInline />
                ) : (
                    <>
                        <EmailTemplaterForm mode="preview" />
                        <EmailTemplaterModal liveChanges={props.liveChanges} saveIndicator={saveIndicator} />
                    </>
                )}
            </div>
        </BindLogic>
    )
}
