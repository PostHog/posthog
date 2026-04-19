import '@react-email/editor/themes/default.css'
import '@react-email/editor/styles/bubble-menu.css'
import '@react-email/editor/styles/slash-command.css'
import './EmailTemplater.scss'

import { EmailEditor, EmailEditorRef } from '@react-email/editor'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { ChildFunctionProps, Form } from 'kea-forms'
import { useCallback, useEffect, useRef, useState } from 'react'

import {
    IconButton,
    IconChevronDown,
    IconChevronLeft,
    IconChevronRight,
    IconCollapse,
    IconColumns,
    IconExpand,
    IconExternal,
    IconImage,
    IconLetter,
    IconList,
    IconMinus,
    IconPlus,
    IconQuote,
    IconX,
} from '@posthog/icons'
import { LemonButton, LemonLabel, LemonMenu, LemonModal, LemonSelect, LemonTabs } from '@posthog/lemon-ui'

import { CyclotronJobTemplateSuggestionsButton } from 'lib/components/CyclotronJob/CyclotronJobTemplateSuggestions'
import { uploadFile } from 'lib/hooks/useUploadFiles'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonColorPicker } from 'lib/lemon-ui/LemonColor/LemonColorPicker'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { urls } from 'scenes/urls'

import 'products/workflows/frontend/TemplateLibrary/MessageTemplatesGrid.scss'
import { MessageTemplateCard } from 'products/workflows/frontend/TemplateLibrary/MessageTemplateCard'

import {
    EMAIL_TYPE_SUPPORTED_FIELDS,
    EmailTemplaterLogicProps,
    emailTemplaterLogic,
    getEditorInitialContent,
} from './emailTemplaterLogic'

export type EmailEditorMode = 'full' | 'preview'

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

const INSPECTOR_PALETTE = [
    '#000000',
    '#374151',
    '#6b7280',
    '#dc2626',
    '#ea580c',
    '#d97706',
    '#65a30d',
    '#059669',
    '#0891b2',
    '#2563eb',
    '#7c3aed',
    '#db2777',
    '#ffffff',
    '#f3f4f6',
]

function parseInlineStyle(style: string | undefined | null): Record<string, string> {
    if (!style) {
        return {}
    }
    return style
        .split(';')
        .map((part) => part.trim())
        .filter(Boolean)
        .reduce<Record<string, string>>((acc, part) => {
            const [prop, ...rest] = part.split(':')
            if (prop && rest.length) {
                acc[prop.trim()] = rest.join(':').trim()
            }
            return acc
        }, {})
}

function stringifyInlineStyle(style: Record<string, string>): string {
    return Object.entries(style)
        .map(([k, v]) => `${k}: ${v}`)
        .join('; ')
}

function mergeStyleAttr(existing: string | undefined | null, updates: Record<string, string | null>): string {
    const parsed = parseInlineStyle(existing)
    for (const [k, v] of Object.entries(updates)) {
        if (v === null || v === '') {
            delete parsed[k]
        } else {
            parsed[k] = v
        }
    }
    return stringifyInlineStyle(parsed)
}

function getActiveBlockType(editor: any): string | null {
    const parent = editor?.state?.selection?.$head?.parent
    return parent?.type?.name ?? null
}

function AlignmentButtons({
    value,
    onChange,
}: {
    value: string | undefined
    onChange: (a: 'left' | 'center' | 'right') => void
}): JSX.Element {
    return (
        <div className="flex gap-1">
            {(['left', 'center', 'right'] as const).map((a) => (
                <LemonButton
                    key={a}
                    size="xsmall"
                    type={value === a ? 'primary' : 'tertiary'}
                    onClick={() => onChange(a)}
                >
                    {a[0].toUpperCase() + a.slice(1)}
                </LemonButton>
            ))}
        </div>
    )
}

function PixelInput({
    value,
    onChange,
    placeholder,
}: {
    value: string | undefined
    onChange: (px: string | null) => void
    placeholder?: string
}): JSX.Element {
    const numeric = value ? parseInt(value, 10) : ''
    return (
        <LemonInput
            size="small"
            type="number"
            value={Number.isFinite(numeric as number) ? (numeric as number) : undefined}
            placeholder={placeholder ?? '0'}
            suffix={<span className="text-secondary text-xs">px</span>}
            onChange={(v) => onChange(v == null || v === 0 ? null : `${v}px`)}
        />
    )
}

function ButtonPanel({ editor }: { editor: any }): JSX.Element {
    const attrs = editor.getAttributes('button')
    const style = parseInlineStyle(attrs?.style)
    const update = (updates: Record<string, string | null>, styleUpdates?: Record<string, string | null>): void => {
        const nextStyle = styleUpdates ? mergeStyleAttr(attrs?.style, styleUpdates) : attrs?.style
        editor
            .chain()
            .focus()
            .updateAttributes('button', { ...attrs, ...updates, style: nextStyle || null })
            .run()
    }
    return (
        <div className="flex flex-col gap-3 p-3">
            <div className="text-xs uppercase tracking-wide text-secondary">Button</div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Link URL</LemonLabel>
                <LemonInput
                    size="small"
                    value={attrs?.href ?? ''}
                    onChange={(v) => update({ href: v || '#' })}
                    placeholder="https://"
                />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Alignment</LemonLabel>
                <AlignmentButtons value={attrs?.alignment} onChange={(a) => update({ alignment: a })} />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Background</LemonLabel>
                <LemonColorPicker
                    colors={INSPECTOR_PALETTE}
                    selectedColor={style['background-color'] ?? null}
                    onSelectColor={(color) => update({}, { 'background-color': color })}
                    showCustomColor
                />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Text color</LemonLabel>
                <LemonColorPicker
                    colors={INSPECTOR_PALETTE}
                    selectedColor={style['color'] ?? null}
                    onSelectColor={(color) => update({}, { color })}
                    showCustomColor
                />
            </div>
        </div>
    )
}

function ImagePanel({ editor }: { editor: any }): JSX.Element {
    const attrs = editor.getAttributes('image')
    const update = (updates: Record<string, string | null>): void => {
        editor.chain().focus().updateAttributes('image', updates).run()
    }
    return (
        <div className="flex flex-col gap-3 p-3">
            <div className="text-xs uppercase tracking-wide text-secondary">Image</div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Source URL</LemonLabel>
                <LemonInput
                    size="small"
                    value={attrs?.src ?? ''}
                    onChange={(v) => update({ src: v })}
                    placeholder="https://"
                />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Alt text</LemonLabel>
                <LemonInput
                    size="small"
                    value={attrs?.alt ?? ''}
                    onChange={(v) => update({ alt: v })}
                    placeholder="Describe this image"
                />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Link URL</LemonLabel>
                <LemonInput
                    size="small"
                    value={attrs?.href ?? ''}
                    onChange={(v) => update({ href: v || null })}
                    placeholder="https://"
                />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Alignment</LemonLabel>
                <AlignmentButtons value={attrs?.alignment} onChange={(a) => update({ alignment: a })} />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Width</LemonLabel>
                <LemonInput
                    size="small"
                    value={attrs?.width ?? ''}
                    onChange={(v) => update({ width: v || 'auto' })}
                    placeholder="auto"
                />
            </div>
        </div>
    )
}

function TextBlockPanel({ editor, blockType }: { editor: any; blockType: string }): JSX.Element {
    const attrs = editor.getAttributes(blockType)
    const style = parseInlineStyle(attrs?.style)
    const updateStyle = (updates: Record<string, string | null>): void => {
        const nextStyle = mergeStyleAttr(attrs?.style, updates)
        editor
            .chain()
            .focus()
            .updateAttributes(blockType, { style: nextStyle || null })
            .run()
    }
    return (
        <div className="flex flex-col gap-3 p-3">
            <div className="text-xs uppercase tracking-wide text-secondary">
                {blockType.charAt(0).toUpperCase() + blockType.slice(1)}
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Text color</LemonLabel>
                <LemonColorPicker
                    colors={INSPECTOR_PALETTE}
                    selectedColor={style['color'] ?? null}
                    onSelectColor={(color) => updateStyle({ color })}
                    showCustomColor
                />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Alignment</LemonLabel>
                <AlignmentButtons
                    value={attrs?.alignment}
                    onChange={(a) => editor.chain().focus().setAlignment(a).run()}
                />
            </div>
        </div>
    )
}

function PageStylePanel({ editor }: { editor: any }): JSX.Element {
    const bodyAttrs = editor.getAttributes('body')
    const bodyStyle = parseInlineStyle(bodyAttrs?.style)

    const updateBodyStyle = (updates: Record<string, string | null>): void => {
        const nextStyle = mergeStyleAttr(bodyAttrs?.style, updates)
        editor
            .chain()
            .focus()
            .updateAttributes('body', { style: nextStyle || null })
            .run()
    }

    const updateBodyAttr = (updates: Record<string, string | null>): void => {
        editor.chain().focus().updateAttributes('body', updates).run()
    }

    return (
        <div className="flex flex-col gap-4 p-3">
            <div className="flex flex-col gap-2">
                <div className="text-xs uppercase tracking-wide text-secondary">Page</div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Background</LemonLabel>
                    <LemonColorPicker
                        colors={INSPECTOR_PALETTE}
                        selectedColor={bodyStyle['background-color'] ?? null}
                        onSelectColor={(color) => updateBodyStyle({ 'background-color': color })}
                        showCustomColor
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Padding</LemonLabel>
                    <PixelInput value={bodyStyle['padding']} onChange={(v) => updateBodyStyle({ padding: v })} />
                </div>
            </div>
            <div className="flex flex-col gap-2">
                <div className="text-xs uppercase tracking-wide text-secondary">Body</div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Text color</LemonLabel>
                    <LemonColorPicker
                        colors={INSPECTOR_PALETTE}
                        selectedColor={bodyStyle['color'] ?? null}
                        onSelectColor={(color) => updateBodyStyle({ color })}
                        showCustomColor
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Width</LemonLabel>
                    <LemonInput
                        size="small"
                        type="number"
                        value={bodyAttrs?.width ? parseInt(String(bodyAttrs.width), 10) : undefined}
                        placeholder="600"
                        suffix={<span className="text-secondary text-xs">px</span>}
                        onChange={(v) => updateBodyAttr({ width: v == null || v === 0 ? null : String(v) })}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Corner radius</LemonLabel>
                    <PixelInput
                        value={bodyStyle['border-radius']}
                        onChange={(v) => updateBodyStyle({ 'border-radius': v })}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Border</LemonLabel>
                    <PixelInput
                        value={bodyStyle['border-width']}
                        onChange={(v) =>
                            updateBodyStyle({
                                'border-width': v,
                                'border-style': v ? 'solid' : null,
                            })
                        }
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Border color</LemonLabel>
                    <LemonColorPicker
                        colors={INSPECTOR_PALETTE}
                        selectedColor={bodyStyle['border-color'] ?? null}
                        onSelectColor={(color) => updateBodyStyle({ 'border-color': color })}
                        showCustomColor
                    />
                </div>
            </div>
        </div>
    )
}

function ElementInspector(): JSX.Element {
    const { emailEditorRef, isEmailEditorReady } = useValues(emailTemplaterLogic)
    const [, setTick] = useState(0)
    const [mode, setMode] = useState<'page' | 'element'>('page')

    useEffect(() => {
        const editor = emailEditorRef?.editor
        if (!editor) {
            return
        }
        const handler = (): void => {
            setTick((t) => t + 1)
            if (editor.isActive('button') || editor.isActive('image')) {
                setMode('element')
            }
        }
        editor.on('selectionUpdate', handler)
        editor.on('transaction', handler)
        return () => {
            editor.off('selectionUpdate', handler)
            editor.off('transaction', handler)
        }
    }, [emailEditorRef])

    const editor = emailEditorRef?.editor
    if (!editor || !isEmailEditorReady) {
        return <div className="EmailTemplater__inspector shrink-0 border-l p-3 text-sm text-secondary">Loading…</div>
    }

    const isButton = editor.isActive('button')
    const isImage = editor.isActive('image')
    const blockType = getActiveBlockType(editor) ?? 'paragraph'

    return (
        <div className="EmailTemplater__inspector flex flex-col shrink-0 border-l">
            <LemonTabs
                activeKey={mode}
                onChange={(k) => setMode(k as 'page' | 'element')}
                className="px-2 shrink-0 border-b"
                tabs={[
                    { key: 'page', label: 'Page style' },
                    { key: 'element', label: 'Element' },
                ]}
            />
            <div className="flex-1 overflow-y-auto">
                {mode === 'page' ? (
                    <PageStylePanel editor={editor} />
                ) : isButton ? (
                    <ButtonPanel editor={editor} />
                ) : isImage ? (
                    <ImagePanel editor={editor} />
                ) : (
                    <TextBlockPanel editor={editor} blockType={blockType} />
                )}
            </div>
        </div>
    )
}

function BlockInserter(): JSX.Element {
    const { emailEditorRef, isEmailEditorReady, mergeTags } = useValues(emailTemplaterLogic)
    const disabledReason = isEmailEditorReady ? undefined : 'Loading…'
    const fileInputRef = useRef<HTMLInputElement>(null)

    const run = (fn: (chain: any) => any): void => {
        const editor = emailEditorRef?.editor
        if (!editor) {
            return
        }
        fn(editor.chain().focus()).run()
    }

    const onImagePicked = async (file: File | null): Promise<void> => {
        if (!file) {
            return
        }
        const blobUrl = URL.createObjectURL(file)
        run((c) => c.setImage({ src: blobUrl }))
        try {
            const { url } = await handleImageUpload(file)
            emailEditorRef?.editor?.chain().focus().updateAttributes('image', { src: url }).run()
        } catch {
            // toast shown inside handleImageUpload
        }
    }

    return (
        <div className="EmailTemplater__rail flex flex-col gap-1 p-1 border-r shrink-0">
            <LemonMenu
                placement="right-start"
                items={[
                    { label: 'Paragraph', onClick: () => run((c) => c.clearNodes().setParagraph()) },
                    {
                        label: 'Heading 1',
                        onClick: () => run((c) => c.clearNodes().toggleHeading({ level: 1 })),
                    },
                    {
                        label: 'Heading 2',
                        onClick: () => run((c) => c.clearNodes().toggleHeading({ level: 2 })),
                    },
                    {
                        label: 'Heading 3',
                        onClick: () => run((c) => c.clearNodes().toggleHeading({ level: 3 })),
                    },
                    { label: 'Bullet list', onClick: () => run((c) => c.clearNodes().toggleBulletList()) },
                    { label: 'Numbered list', onClick: () => run((c) => c.clearNodes().toggleOrderedList()) },
                    { label: 'Blockquote', onClick: () => run((c) => c.clearNodes().toggleBlockquote()) },
                ]}
            >
                <LemonButton size="small" icon={<IconLetter />} tooltip="Text" disabledReason={disabledReason} />
            </LemonMenu>
            <LemonButton
                size="small"
                icon={<IconImage />}
                tooltip="Image"
                disabledReason={disabledReason}
                onClick={() => fileInputRef.current?.click()}
            />
            <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                    const file = e.target.files?.[0] ?? null
                    e.target.value = ''
                    void onImagePicked(file)
                }}
            />
            <LemonButton
                size="small"
                icon={<IconButton />}
                tooltip="Button"
                disabledReason={disabledReason}
                onClick={() => run((c) => c.setButton())}
            />
            <LemonButton
                size="small"
                icon={<IconList />}
                tooltip="Bullet list"
                disabledReason={disabledReason}
                onClick={() => run((c) => c.clearNodes().toggleBulletList())}
            />
            <LemonButton
                size="small"
                icon={<IconQuote />}
                tooltip="Blockquote"
                disabledReason={disabledReason}
                onClick={() => run((c) => c.clearNodes().toggleBlockquote())}
            />
            <LemonButton
                size="small"
                icon={<IconMinus />}
                tooltip="Divider"
                disabledReason={disabledReason}
                onClick={() => run((c) => c.setHorizontalRule())}
            />
            <LemonMenu
                placement="right-start"
                items={[
                    { label: 'Section', onClick: () => run((c) => c.insertSection()) },
                    { label: '2 columns', onClick: () => run((c) => c.insertColumns(2)) },
                    { label: '3 columns', onClick: () => run((c) => c.insertColumns(3)) },
                    { label: '4 columns', onClick: () => run((c) => c.insertColumns(4)) },
                ]}
            >
                <LemonButton size="small" icon={<IconColumns />} tooltip="Layout" disabledReason={disabledReason} />
            </LemonMenu>
            {mergeTags.length > 0 && (
                <LemonMenu
                    placement="right-start"
                    items={mergeTags.map((tag) => ({
                        label: tag.label,
                        onClick: () => run((c) => c.insertContent(tag.value)),
                    }))}
                >
                    <LemonButton
                        size="small"
                        icon={<IconPlus />}
                        tooltip="Insert merge tag"
                        disabledReason={disabledReason}
                    />
                </LemonMenu>
            )}
        </div>
    )
}

async function handleImageUpload(file: File): Promise<{ url: string }> {
    try {
        const response = await uploadFile(file)
        return { url: response.image_location }
    } catch (e: any) {
        lemonToast.error(`Failed to upload image: ${e?.message ?? 'unknown error'}`)
        throw e
    }
}

function VisualEmailEditor(): JSX.Element {
    const { logicProps, isEmailEditorReady } = useValues(emailTemplaterLogic)
    const { setEmailEditorRef, onEmailEditorReady } = useActions(emailTemplaterLogic)
    // Initial content is a one-shot read on mount — the editor manages its own state after that.
    const initialContentRef = useRef(getEditorInitialContent(logicProps.value))

    return (
        <div className="flex flex-1 min-h-0 overflow-hidden">
            <BlockInserter />
            <div className={clsx('EmailTemplater__canvas flex-1 min-h-0', !isEmailEditorReady && 'opacity-50')}>
                <EmailEditor
                    ref={(r: EmailEditorRef | null) => setEmailEditorRef(r)}
                    content={initialContentRef.current}
                    onReady={() => onEmailEditorReady()}
                    onUploadImage={handleImageUpload}
                    className="EmailTemplater__canvas-inner"
                />
            </div>
            <ElementInspector />
        </div>
    )
}

function DestinationEmailTemplaterForm({
    mode,
    fieldsHidden,
}: {
    mode: EmailEditorMode
    fieldsHidden?: boolean
}): JSX.Element {
    const { logicProps, activeContentTab } = useValues(emailTemplaterLogic)
    const { setIsModalOpen, setActiveContentTab } = useActions(emailTemplaterLogic)

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
                        <LemonTabs
                            activeKey={activeContentTab}
                            onChange={(key) => setActiveContentTab(key as 'visual' | 'plaintext')}
                            tabs={[
                                { key: 'visual', label: 'Visual' },
                                { key: 'plaintext', label: 'Plain text' },
                            ]}
                            className="px-2 shrink-0 border-b"
                        />
                        <div className="relative flex flex-col flex-1 min-h-0">
                            <div
                                className={clsx(
                                    activeContentTab === 'visual'
                                        ? 'flex flex-col flex-1 min-h-0'
                                        : 'absolute inset-0 -z-10 opacity-0 pointer-events-none'
                                )}
                            >
                                <VisualEmailEditor />
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

                                <iframe srcDoc={value} sandbox="" title="Email template preview" className="flex-1" />
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
    fieldsHidden,
    onSaveAsTemplate,
}: {
    mode: EmailEditorMode
    fieldsHidden?: boolean
    onSaveAsTemplate?: () => void
}): JSX.Element {
    const { logicProps, templates, activeContentTab, visibleFields } = useValues(emailTemplaterLogic)
    const { setIsModalOpen, applyTemplate, setActiveContentTab, hideAdvancedField } = useActions(emailTemplaterLogic)

    const [previewTemplate, setPreviewTemplate] = useState<(typeof templates)[0] | null>(null)

    return (
        <>
            <Form
                {...{ className: 'flex overflow-hidden flex-col flex-1 rounded border' }}
                logic={emailTemplaterLogic}
                props={logicProps}
                formKey="emailTemplate"
            >
                <div className={fieldsHidden ? 'h-0 overflow-hidden' : ''}>
                    {visibleFields.map((field) => (
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
                            )}
                        </LemonField>
                    ))}

                    <AddAdvancedFieldButtons />

                    {mode === 'full' && templates.length > 0 && (
                        <TemplateSlider
                            templates={templates}
                            onSelect={applyTemplate}
                            onSaveAsTemplate={onSaveAsTemplate}
                        />
                    )}
                </div>

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
                        <div className="relative flex flex-col flex-1 min-h-0">
                            <div
                                className={clsx(
                                    activeContentTab === 'visual'
                                        ? 'flex flex-col flex-1 min-h-0'
                                        : 'absolute inset-0 -z-10 opacity-0 pointer-events-none'
                                )}
                            >
                                <VisualEmailEditor />
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
                                    title="Email template preview"
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

                                <iframe srcDoc={value} sandbox="" title="Email template preview" className="flex-1" />
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
    fieldsHidden,
    onSaveAsTemplate,
}: {
    mode: EmailEditorMode
    fieldsHidden?: boolean
    onSaveAsTemplate?: () => void
}): JSX.Element {
    const { logicProps } = useValues(emailTemplaterLogic)

    switch (logicProps.type) {
        case 'email':
            return <DestinationEmailTemplaterForm mode={mode} fieldsHidden={fieldsHidden} />
        case 'native_email_template':
        case 'native_email':
            return (
                <NativeEmailTemplaterForm mode={mode} fieldsHidden={fieldsHidden} onSaveAsTemplate={onSaveAsTemplate} />
            )
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
    const [fieldsHidden, setFieldsHidden] = useState(false)

    useEffect(() => {
        if (!isModalOpen) {
            setFieldsHidden(false)
        }
    }, [isModalOpen])

    return (
        <>
            <LemonModal
                isOpen={isModalOpen}
                width="90vw"
                onClose={() => closeWithConfirmation()}
                hasUnsavedInput={emailTemplateChanged}
            >
                <div className="h-[85vh] flex relative">
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={fieldsHidden ? <IconExpand /> : <IconCollapse />}
                        onClick={() => setFieldsHidden(!fieldsHidden)}
                        className="absolute -top-1 right-10 z-10"
                    >
                        {fieldsHidden ? 'Show fields' : 'Hide fields'}
                    </LemonButton>
                    <div className="flex flex-col flex-1">
                        <div className="shrink-0">
                            <h2>Editing email template</h2>
                        </div>
                        <EmailTemplaterForm
                            mode="full"
                            fieldsHidden={fieldsHidden}
                            onSaveAsTemplate={() => setIsSaveTemplateModalOpen(true)}
                        />
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
