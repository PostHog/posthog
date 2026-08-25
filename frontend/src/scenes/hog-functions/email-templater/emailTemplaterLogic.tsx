import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { Editor, EmailEditorProps, EditorRef as _EditorRef } from 'react-email-editor'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { objectsEqual } from 'lib/utils/objects'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { PreflightStatus, PropertyDefinition, PropertyDefinitionType, Realm } from '~/types'

import { MessageTemplate } from 'products/workflows/frontend/TemplateLibrary/types'

import type { EmailFieldErrors, EmailTemplate } from './types'

export type { EmailTemplate }

export type UnlayerMergeTags = NonNullable<EmailEditorProps['options']>['mergeTags']

/**
 * email: basic email editor with free-text fields, used for configuring email platform realtime destinations
 * native_email: advanced editor with email integration dropdown, and additional email metafields
 * native_email_template: editor for creating reusable templates, with only subject and preheader, and email content fields
 */
export type EmailTemplaterType = 'email' | 'native_email' | 'native_email_template'
export type EmailMetaFieldKey = 'from' | 'to' | 'replyTo' | 'cc' | 'bcc' | 'subject' | 'preheader'
export type EmailMetaField = {
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
        isAdvancedField: true,
        helpText: 'Optional reply-to email address. You can comma separate multiple reply-to addresses.',
    },
    CC: {
        key: 'cc',
        label: 'Cc',
        optional: true,
        isAdvancedField: true,
        helpText: 'Comma-separated list of CC recipients.',
    },
    BCC: {
        key: 'bcc',
        label: 'Bcc',
        optional: true,
        isAdvancedField: true,
        helpText: 'Comma-separated list of BCC recipients.',
    },
    PREHEADER: {
        key: 'preheader',
        label: 'Preheader',
        optional: true,
        isAdvancedField: true,
        helpText: 'This is the preview text that appears below the subject line in an inbox.',
    },
    SUBJECT: { key: 'subject', label: 'Subject', optional: false },
} as const

export const EMAIL_TYPE_SUPPORTED_FIELDS: Record<EmailTemplaterType, EmailMetaField[]> = {
    email: [EMAIL_META_FIELDS.FROM, EMAIL_META_FIELDS.TO, EMAIL_META_FIELDS.SUBJECT],
    native_email: [
        EMAIL_META_FIELDS.FROM,
        EMAIL_META_FIELDS.TO,
        EMAIL_META_FIELDS.REPLY_TO,
        EMAIL_META_FIELDS.CC,
        EMAIL_META_FIELDS.BCC,
        EMAIL_META_FIELDS.SUBJECT,
        EMAIL_META_FIELDS.PREHEADER,
    ],
    native_email_template: [EMAIL_META_FIELDS.SUBJECT, EMAIL_META_FIELDS.PREHEADER],
}

// Helping kea-typegen navigate the exported type
export interface EditorRef extends _EditorRef {}

type JSONTemplate = Parameters<Editor['loadDesign']>[0]

/**
 * Wrap raw html in an Unlayer design holding a single custom HTML block. Emails authored
 * programmatically (API/MCP) often have html but no design; loading a wrapped design shows the
 * email in the canvas instead of a blank editor whose save would clobber the stored html.
 * Mirrors build_html_wrap_design in posthog/cdp/validation.py.
 */
export function buildHtmlWrapDesign(html: string): JSONTemplate {
    // Fixed ids keep the wrap deterministic: re-wrapping the same html yields an identical
    // design, so backend content-equality checks (revisions, draft diffing) see no change.
    return {
        counters: { u_row: 1, u_column: 1, u_content_html: 1 },
        schemaVersion: 16,
        body: {
            id: 'html-wrap-body',
            headers: [],
            footers: [],
            rows: [
                {
                    id: 'html-wrap-row',
                    cells: [1],
                    columns: [
                        {
                            id: 'html-wrap-column',
                            contents: [
                                {
                                    id: 'html-wrap-content',
                                    type: 'html',
                                    values: {
                                        html,
                                        _meta: { htmlID: 'u_content_html_1', htmlClassNames: 'u_content_html' },
                                    },
                                },
                            ],
                            values: { _meta: { htmlID: 'u_column_1', htmlClassNames: 'u_column' } },
                        },
                    ],
                    values: { _meta: { htmlID: 'u_row_1', htmlClassNames: 'u_row' } },
                },
            ],
            values: {},
        },
    } as unknown as JSONTemplate
}

// URL reflection for the fullscreen editor (?editor=email), so back, Escape, and deep links work.
const EMAIL_EDITOR_URL_PARAM = 'editor'
const EMAIL_EDITOR_URL_VALUE = 'email'

export interface EmailTemplaterLogicProps {
    value: EmailTemplate | null
    onChange: (value: EmailTemplate) => void
    variables?: Record<string, any>
    type: EmailTemplaterType
    defaultValue?: EmailTemplate | null
    templating?: boolean | 'hog' | 'liquid'
    onChangeTemplating?: (templating: 'hog' | 'liquid') => void
    /**
     * 'modal' (default): preview with an editing modal, changes propagate on save.
     * 'inline': the full editor rendered in place, changes propagate live (debounced) so the
     * parent form's dirty state and save flow see them without a separate editor-level save.
     */
    layout?: 'modal' | 'inline'
    /**
     * Propagate edits live (debounced) in the modal layout too, for hosts that persist changes
     * themselves (the workflow builder's auto-save). The modal loses its save/discard step, and an
     * externally changed props.value.design (e.g. an AI assistant editing the same email) reloads
     * the open Unlayer canvas.
     */
    liveChanges?: boolean
    // Validation messages owned by the parent form, shown next to each field. The templater does
    // not compute these itself; a caller that validates the email step (e.g. the workflow builder)
    // decides what and when to show.
    fieldErrors?: EmailFieldErrors
}

function autoRevealAdvancedFields(
    actions: { revealAdvancedField: (key: EmailMetaFieldKey) => void },
    props: EmailTemplaterLogicProps
): void {
    if (!props.value) {
        return
    }
    for (const field of EMAIL_TYPE_SUPPORTED_FIELDS[props.type]) {
        if (field.isAdvancedField) {
            const value = (props.value as Record<string, any>)[field.key]
            if (value !== undefined && value !== null && value !== '') {
                actions.revealAdvancedField(field.key as EmailMetaFieldKey)
            }
        }
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface emailTemplaterLogicValues {
    preflight: PreflightStatus | null // preflightLogic
    activeContentTab: 'plaintext' | 'visual'
    appliedTemplate: MessageTemplate | null
    emailEditorRef: EditorRef | null
    emailTemplate: EmailTemplate
    emailTemplateAllErrors: Record<string, any>
    emailTemplateChanged: boolean
    emailTemplateErrors: DeepPartialMap<EmailTemplate, ValidationErrorType>
    emailTemplateHasErrors: boolean
    emailTemplateManualErrors: Record<string, any>
    emailTemplateTouched: boolean
    emailTemplateTouches: Record<string, boolean>
    emailTemplateValidationErrors: DeepPartialMap<EmailTemplate, ValidationErrorType>
    hiddenAdvancedFields: EmailMetaField[]
    isEmailEditorReady: boolean
    isEmailTemplateSubmitting: boolean
    isEmailTemplateValid: boolean
    isModalOpen: boolean
    isSaveTemplateModalOpen: boolean
    isTemplatePickerOpen: boolean
    logicProps: EmailTemplaterLogicProps
    mergeTags: UnlayerMergeTags
    personPropertyDefinitions: PropertyDefinition[]
    personPropertyDefinitionsLoading: boolean
    revealedAdvancedFields: EmailMetaFieldKey[]
    showEmailTemplateErrors: boolean
    templates: MessageTemplate[]
    templatesLoading: boolean
    templatingEngine: 'hog' | 'liquid'
    unlayerEditorProjectId: 275430 | undefined
    visibleFields: EmailMetaField[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface emailTemplaterLogicActions {
    applyTemplate: (template: MessageTemplate) => {
        template: MessageTemplate
    }
    closeWithConfirmation: () => {
        value: true
    }
    designLoaded: () => {
        value: true
    }
    designUpdated: () => {
        value: true
    }
    hideAdvancedField: (key: EmailMetaFieldKey) => {
        key: EmailMetaFieldKey
    }
    loadPersonPropertyDefinitions: () => any
    loadPersonPropertyDefinitionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPersonPropertyDefinitionsSuccess: (
        personPropertyDefinitions: PropertyDefinition[],
        payload?: any
    ) => {
        personPropertyDefinitions: PropertyDefinition[]
        payload?: any
    }
    loadTemplates: () => any
    loadTemplatesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadTemplatesSuccess: (
        templates: MessageTemplate[],
        payload?: any
    ) => {
        templates: MessageTemplate[]
        payload?: any
    }
    onEmailEditorReady: () => {
        value: true
    }
    resetEmailTemplate: (values?: EmailTemplate) => {
        values?: EmailTemplate
    }
    revealAdvancedField: (key: EmailMetaFieldKey) => {
        key: EmailMetaFieldKey
    }
    saveAsTemplate: (
        name: string,
        description: string
    ) => {
        description: string
        name: string
    }
    setActiveContentTab: (tab: 'plaintext' | 'visual') => {
        tab: 'plaintext' | 'visual'
    }
    setEmailEditorRef: (emailEditorRef: EditorRef | null) => {
        emailEditorRef: EditorRef | null
    }
    setEmailTemplateManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setEmailTemplateValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setEmailTemplateValues: (values: DeepPartial<EmailTemplate>) => {
        values: DeepPartial<EmailTemplate>
    }
    setIsModalOpen: (isModalOpen: boolean) => {
        isModalOpen: boolean
    }
    setIsSaveTemplateModalOpen: (isOpen: boolean) => {
        isOpen: boolean
    }
    setIsTemplatePickerOpen: (isOpen: boolean) => {
        isOpen: boolean
    }
    setTemplatingEngine: (templating: 'hog' | 'liquid') => {
        templating: 'hog' | 'liquid'
    }
    submitEmailTemplate: () => {
        value: boolean
    }
    submitEmailTemplateFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitEmailTemplateRequest: (emailTemplate: EmailTemplate) => {
        emailTemplate: EmailTemplate
    }
    submitEmailTemplateSuccess: (emailTemplate: EmailTemplate) => {
        emailTemplate: EmailTemplate
    }
    touchEmailTemplateField: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface emailTemplaterLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        logicProps: (arg: any) => EmailTemplaterLogicProps
        mergeTags: (personPropertyDefinitions: PropertyDefinition[]) => UnlayerMergeTags
        unlayerEditorProjectId: (preflight: PreflightStatus | null) => 275430 | undefined
        visibleFields: (arg: EmailTemplaterType, revealedAdvancedFields: EmailMetaFieldKey[]) => EmailMetaField[]
        hiddenAdvancedFields: (arg: EmailTemplaterType, visibleFields: EmailMetaField[]) => EmailMetaField[]
    }
}

export type emailTemplaterLogicType = MakeLogicType<
    emailTemplaterLogicValues,
    emailTemplaterLogicActions,
    EmailTemplaterLogicProps,
    emailTemplaterLogicMeta
>

export const emailTemplaterLogic = kea<emailTemplaterLogicType>([
    props({} as EmailTemplaterLogicProps),
    path(['scenes', 'hog-functions', 'email-templater', 'emailTemplaterLogic']),
    connect(() => ({
        values: [preflightLogic, ['preflight']],
    })),
    actions({
        setEmailEditorRef: (emailEditorRef: EditorRef | null) => ({ emailEditorRef }),
        onEmailEditorReady: true,
        setIsModalOpen: (isModalOpen: boolean) => ({ isModalOpen }),
        setIsSaveTemplateModalOpen: (isOpen: boolean) => ({ isOpen }),
        setIsTemplatePickerOpen: (isOpen: boolean) => ({ isOpen }),
        designUpdated: true,
        designLoaded: true,
        applyTemplate: (template: MessageTemplate) => ({ template }),
        closeWithConfirmation: true,
        setTemplatingEngine: (templating: 'hog' | 'liquid') => ({ templating }),
        saveAsTemplate: (name: string, description: string) => ({ name, description }),
        setActiveContentTab: (tab: 'visual' | 'plaintext') => ({ tab }),
        revealAdvancedField: (key: EmailMetaFieldKey) => ({ key }),
        hideAdvancedField: (key: EmailMetaFieldKey) => ({ key }),
    }),
    reducers({
        emailEditorRef: [
            null as EditorRef | null,
            {
                setEmailEditorRef: (_, { emailEditorRef }) => emailEditorRef,
            },
        ],
        isEmailEditorReady: [
            false,
            {
                setIsModalOpen: () => false,
                onEmailEditorReady: () => true,
            },
        ],
        isModalOpen: [
            false,
            {
                setIsModalOpen: (_, { isModalOpen }) => isModalOpen,
            },
        ],
        isSaveTemplateModalOpen: [
            false,
            {
                setIsSaveTemplateModalOpen: (_, { isOpen }) => isOpen,
            },
        ],
        isTemplatePickerOpen: [
            false,
            {
                setIsTemplatePickerOpen: (_, { isOpen }) => isOpen,
                setIsModalOpen: (state, { isModalOpen }) => (isModalOpen ? state : false),
            },
        ],
        appliedTemplate: [
            null as MessageTemplate | null,
            {
                applyTemplate: (_, { template }) => template,
            },
        ],
        templatingEngine: [
            'liquid' as 'hog' | 'liquid',
            {
                setTemplatingEngine: (_, { templating }) => {
                    return templating
                },
            },
        ],
        revealedAdvancedFields: [
            [] as EmailMetaFieldKey[],
            {
                revealAdvancedField: (state: EmailMetaFieldKey[], { key }: { key: EmailMetaFieldKey }) =>
                    state.includes(key) ? state : [...state, key],
                hideAdvancedField: (state: EmailMetaFieldKey[], { key }: { key: EmailMetaFieldKey }) =>
                    state.filter((k) => k !== key),
            },
        ],
        activeContentTab: [
            'visual' as 'visual' | 'plaintext',
            {
                setActiveContentTab: (_, { tab }) => tab,
                applyTemplate: (_, { template }) => {
                    const hasHtml = !!template.content.email.html
                    return hasHtml ? 'visual' : 'plaintext'
                },
            },
        ],
    }),

    loaders(() => ({
        templates: [
            [] as MessageTemplate[],
            {
                loadTemplates: async () => {
                    const response = await api.messaging.getTemplates()
                    return response.results
                },
            },
        ],
        personPropertyDefinitions: [
            [] as PropertyDefinition[],
            {
                loadPersonPropertyDefinitions: async () => {
                    const response = await api.propertyDefinitions.list({
                        type: PropertyDefinitionType.Person,
                        limit: 1000, // Get a large number of person properties
                    })
                    return response.results
                },
            },
        ],
    })),

    selectors({
        logicProps: [() => [(_, props) => props], (props: EmailTemplaterLogicProps) => props],
        mergeTags: [
            (s) => [s.personPropertyDefinitions],
            (personPropertyDefinitions: PropertyDefinition[]): UnlayerMergeTags => {
                const tags: UnlayerMergeTags = {
                    unsubscribe_url: {
                        name: 'Unsubscribe URL',
                        value: '{{unsubscribe_url}}',
                        sample: 'https://example.com/unsubscribe/12345',
                    },
                    unsubscribe_url_one_click: {
                        name: 'One-Click Unsubscribe URL',
                        value: '{{unsubscribe_url_one_click}}',
                        sample: 'https://example.com/unsubscribe/12345?one_click_unsubscribe=1',
                    },
                }

                // Add person properties as merge tags
                personPropertyDefinitions.forEach((property: PropertyDefinition) => {
                    tags[property.name] = {
                        name: property.name,
                        value: `{{person.properties["${property.name}"]}}`,
                        sample: property.example || `Sample ${property.name}`,
                    }
                })

                return tags
            },
        ],
        unlayerEditorProjectId: [
            (s) => [s.preflight],
            (preflight: PreflightStatus) => {
                if (preflight.realm === Realm.Cloud || preflight.is_debug) {
                    return 275430
                }
            },
        ],
        visibleFields: [
            (s) => [(_, props: EmailTemplaterLogicProps) => props.type, s.revealedAdvancedFields],
            (type: EmailTemplaterType, revealedAdvancedFields: EmailMetaFieldKey[]): EmailMetaField[] =>
                EMAIL_TYPE_SUPPORTED_FIELDS[type].filter(
                    (field) => !field.isAdvancedField || revealedAdvancedFields.includes(field.key)
                ),
        ],
        hiddenAdvancedFields: [
            (s) => [(_, props: EmailTemplaterLogicProps) => props.type, s.visibleFields],
            (type: EmailTemplaterType, visibleFields: EmailMetaField[]): EmailMetaField[] =>
                EMAIL_TYPE_SUPPORTED_FIELDS[type].filter((f) => f.isAdvancedField && !visibleFields.includes(f)),
        ],
    }),

    forms(({ actions, values, props, cache }) => ({
        emailTemplate: {
            defaults: props.defaultValue as EmailTemplate,
            submit: async (formValues: EmailTemplate | undefined) => {
                if (!formValues) {
                    return
                }

                if (values.activeContentTab === 'plaintext') {
                    const finalValues: EmailTemplate = {
                        ...formValues,
                        html: '',
                    }
                    props.onChange(finalValues)
                    actions.setIsModalOpen(false)
                    return
                }

                const editor = values.emailEditorRef?.editor
                if (!editor || !values.isEmailEditorReady) {
                    return
                }

                const [htmlData, textData]: [{ html: string; design: JSONTemplate }, { text: string }] =
                    await Promise.all([
                        new Promise<any>((res) => editor.exportHtml(res)),
                        new Promise<any>((res) => editor.exportPlainText(res)),
                    ])

                // A save with no canvas edits keeps the stored html/text/design byte-identical
                // instead of replacing them with the editor's re-render - the export wraps raw
                // html emails in Unlayer chrome, so an unconditional overwrite would silently
                // change what recipients receive on a no-op save. Meta field edits still apply.
                if (objectsEqual(htmlData.design, cache.lastEditorDesign)) {
                    props.onChange({ ...formValues })
                    actions.setIsModalOpen(false)
                    return
                }

                const finalValues: EmailTemplate = {
                    ...formValues,
                    html: ['native_email', 'native_email_template'].includes(props.type)
                        ? htmlData.html
                        : escapeHTMLStringCurlies(htmlData.html),
                    text: textData.text,
                    design: htmlData.design,
                }

                cache.lastEditorDesign = htmlData.design
                props.onChange(finalValues)
                actions.setIsModalOpen(false)
            },
        },
    })),

    listeners(({ props, values, actions, cache }) => ({
        onEmailEditorReady: () => {
            // Listeners must attach before loadDesign so the initial design:loaded is heard and
            // rebaselines - otherwise the load echo is indistinguishable from a user edit.
            if (props.layout === 'inline' || props.liveChanges) {
                values.emailEditorRef?.editor?.addEventListener('design:updated', () => actions.designUpdated())
            }
            // Both layouts rebaseline on load: the modal submit compares its export against the
            // baseline to tell a no-op save from a real edit.
            values.emailEditorRef?.editor?.addEventListener('design:loaded', () => actions.designLoaded())
            if (props.value?.design) {
                cache.lastEditorDesign = props.value.design
                values.emailEditorRef?.editor?.loadDesign(props.value.design)
            } else if (props.value?.html) {
                const wrapped = buildHtmlWrapDesign(props.value.html)
                cache.lastEditorDesign = wrapped
                values.emailEditorRef?.editor?.loadDesign(wrapped)
            }
        },

        designLoaded: async (_, breakpoint) => {
            // Re-baseline off the editor's own normalized export: unlayer rewrites loaded JSON
            // (defaults, ids), so comparing raw stored designs against later exports would flag
            // every load echo as an edit and falsely dirty the parent form.
            const editor = values.emailEditorRef?.editor
            if (!editor) {
                return
            }
            const htmlData: { design: JSONTemplate } = await new Promise<any>((res) => editor.exportHtml(res))
            breakpoint()
            cache.lastEditorDesign = htmlData.design
        },

        designUpdated: async (_, breakpoint) => {
            // A programmatic loadDesign fires design:updated too; the debounce lets designLoaded
            // rebaseline first, and the equality check below then filters the echo. A genuine user
            // edit differs from the baseline, so it always propagates - even right after a load.
            // While this is pending, the canvas may hold an edit the parent hasn't seen yet, so
            // propsChanged must not load an external design over it (the flag below guards that).
            cache.pendingDesignEdit = true
            await breakpoint(500)

            const editor = values.emailEditorRef?.editor
            if (!editor || !values.isEmailEditorReady) {
                cache.pendingDesignEdit = false
                return
            }

            const [htmlData, textData]: [{ html: string; design: JSONTemplate }, { text: string }] = await Promise.all([
                new Promise<any>((res) => editor.exportHtml(res)),
                new Promise<any>((res) => editor.exportPlainText(res)),
            ])
            breakpoint()
            cache.pendingDesignEdit = false

            // Only real changes propagate - an export identical to the last known editor state is a
            // load echo, and pushing it would only mark the parent form dirty.
            if (objectsEqual(htmlData.design, cache.lastEditorDesign)) {
                return
            }
            cache.lastEditorDesign = htmlData.design
            // The user now owns the canvas: if an external editor later reverts to a design we once
            // pushed in, it must load again rather than be skipped as already applied.
            cache.lastLoadedExternalDesign = null
            props.onChange({
                ...values.emailTemplate,
                html: ['native_email', 'native_email_template'].includes(props.type)
                    ? htmlData.html
                    : escapeHTMLStringCurlies(htmlData.html),
                text: textData.text,
                design: htmlData.design,
            })
        },

        setEmailTemplateValue: ({ name, value }) => {
            if (values.isModalOpen && !props.liveChanges) {
                // When open we only update on save
                return
            }

            if (name === 'html') {
                return
            }

            const key = Array.isArray(name) ? name[0] : name

            props.onChange({
                ...props.value,
                [key]: value,
                // Plain-text authoring replaces the html body (the modal save does this too);
                // without it the stale html keeps winning over the text at send time.
                ...(key === 'text' && values.activeContentTab === 'plaintext' ? { html: '' } : {}),
            } as EmailTemplate)
        },

        setEmailTemplateValues: ({ values }) => {
            props.onChange({
                ...props.value,
                ...values,
            } as EmailTemplate)
        },

        setIsModalOpen: ({ isModalOpen }) => {
            if (isModalOpen && props.value) {
                // Plain text only when the email is genuinely text-only; a blank email starts visual.
                const plainTextOnly = !!props.value.text && !props.value.html && !props.value.design
                actions.setActiveContentTab(plainTextOnly ? 'plaintext' : 'visual')
            }
        },

        applyTemplate: ({ template }) => {
            const emailTemplateContent = template.content.email
            actions.setEmailTemplateValues(emailTemplateContent)

            // Load the design into the editor if it's ready and has a design
            if (values.isEmailEditorReady && emailTemplateContent.design) {
                cache.lastEditorDesign = emailTemplateContent.design
                values.emailEditorRef?.editor?.loadDesign(emailTemplateContent.design)
            }
        },

        closeWithConfirmation: async () => {
            // With live changes there is nothing unsaved to discard; edits already propagated.
            if (values.emailTemplateChanged && !props.liveChanges) {
                LemonDialog.open({
                    title: 'Discard changes',
                    description: 'Are you sure you want to discard your changes?',
                    primaryButton: {
                        onClick: () => {
                            actions.resetEmailTemplate(props.value ?? undefined)
                            actions.setIsModalOpen(false)
                        },
                        children: 'Discard',
                    },
                    secondaryButton: {
                        children: 'Keep editing',
                    },
                })
                return
            }
            // A canvas edit made in the last 500ms is still inside designUpdated's debounce; closing
            // unmounts the editor before it exports, silently dropping that edit. Flush it now,
            // while the editor is still mounted. The debounced continuation then no-ops (or never
            // resolves post-unmount), since lastEditorDesign already matches.
            if (props.liveChanges && cache.pendingDesignEdit && values.isEmailEditorReady) {
                const editor = values.emailEditorRef?.editor
                if (editor) {
                    const [htmlData, textData]: [{ html: string; design: JSONTemplate }, { text: string }] =
                        await Promise.all([
                            new Promise<any>((res) => editor.exportHtml(res)),
                            new Promise<any>((res) => editor.exportPlainText(res)),
                        ])
                    cache.pendingDesignEdit = false
                    if (!objectsEqual(htmlData.design, cache.lastEditorDesign)) {
                        cache.lastEditorDesign = htmlData.design
                        cache.lastLoadedExternalDesign = null
                        props.onChange({
                            ...values.emailTemplate,
                            html: ['native_email', 'native_email_template'].includes(props.type)
                                ? htmlData.html
                                : escapeHTMLStringCurlies(htmlData.html),
                            text: textData.text,
                            design: htmlData.design,
                        })
                    }
                }
            }
            actions.setIsModalOpen(false)
        },

        saveAsTemplate: async ({ name, description }) => {
            const currentValues = values.emailTemplate

            try {
                let emailContent: EmailTemplate

                if (values.activeContentTab === 'plaintext') {
                    emailContent = {
                        ...currentValues,
                        html: '',
                    }
                } else {
                    const editor = values.emailEditorRef?.editor
                    if (!editor || !values.isEmailEditorReady) {
                        lemonToast.error('Editor not ready')
                        return
                    }

                    const [htmlData, textData]: [{ html: string; design: JSONTemplate }, { text: string }] =
                        await Promise.all([
                            new Promise<any>((res) => editor.exportHtml(res)),
                            new Promise<any>((res) => editor.exportPlainText(res)),
                        ])

                    emailContent = {
                        ...currentValues,
                        html: ['native_email', 'native_email_template'].includes(props.type)
                            ? htmlData.html
                            : escapeHTMLStringCurlies(htmlData.html),
                        text: textData.text,
                        design: htmlData.design,
                    }
                }

                const templateData: Partial<MessageTemplate> = {
                    name,
                    description,
                    content: {
                        templating: values.templatingEngine,
                        email: emailContent,
                    },
                }

                await api.messaging.createTemplate(templateData)
                lemonToast.success('Template saved successfully')
                actions.loadTemplates()
                actions.setIsSaveTemplateModalOpen(false)
            } catch (error) {
                lemonToast.error('Failed to save template')
                console.error(error)
            }
        },
    })),

    actionToUrl(({ props }) => ({
        setIsModalOpen: ({ isModalOpen }) => {
            // Inline layouts render no editor container; leave their URLs untouched.
            if (props.layout === 'inline') {
                return undefined
            }
            const { pathname, searchParams, hashParams } = router.values.currentLocation
            // Already in sync (e.g. closed by the back button): pushing again would add a
            // duplicate history entry and break forward/back.
            if (isModalOpen === (searchParams[EMAIL_EDITOR_URL_PARAM] === EMAIL_EDITOR_URL_VALUE)) {
                return undefined
            }
            const next = { ...searchParams }
            if (isModalOpen) {
                next[EMAIL_EDITOR_URL_PARAM] = EMAIL_EDITOR_URL_VALUE
            } else {
                delete next[EMAIL_EDITOR_URL_PARAM]
            }
            // A push, not a replace: the browser back button closes the editor.
            return [pathname, next, hashParams]
        },
    })),

    urlToAction(({ actions, values, props }) => ({
        '*': (_, searchParams) => {
            if (props.layout === 'inline') {
                return
            }
            const shouldBeOpen = searchParams[EMAIL_EDITOR_URL_PARAM] === EMAIL_EDITOR_URL_VALUE
            if (shouldBeOpen === values.isModalOpen) {
                return
            }
            if (!shouldBeOpen && props.liveChanges) {
                // Browser back closes through here rather than the Done button; route it through
                // the same flush so a canvas edit still inside the design debounce isn't lost.
                // The URL already lacks the param, so the close's actionToUrl echo is a no-op.
                actions.closeWithConfirmation()
                return
            }
            actions.setIsModalOpen(shouldBeOpen)
        },
    })),

    propsChanged(({ actions, props, values, cache }, oldProps) => {
        if (props.value && !objectsEqual(props.value, oldProps.value)) {
            actions.resetEmailTemplate(props.value)
            autoRevealAdvancedFields(actions, props)

            // resetEmailTemplate refreshes the form fields, but the mounted Unlayer canvas only
            // loads a design on editor-ready or template-apply, so an externally changed design (an
            // AI assistant or another tab editing this email) must be pushed in here. Our own edits
            // round-trip back through the parent equal to the last export (or the last pushed
            // design) and are skipped. A local canvas edit whose debounce hasn't flushed yet wins
            // over the incoming design: its onChange is about to overwrite the same fields anyway.
            if (
                (props.layout === 'inline' || props.liveChanges) &&
                values.isEmailEditorReady &&
                !cache.pendingDesignEdit
            ) {
                const design = props.value.design ?? (props.value.html ? buildHtmlWrapDesign(props.value.html) : null)
                if (
                    design &&
                    !objectsEqual(design, cache.lastEditorDesign) &&
                    !objectsEqual(design, cache.lastLoadedExternalDesign)
                ) {
                    // lastEditorDesign is set pre-load so the design:updated echo of this load is
                    // filtered; design:loaded then rebaselines it to the editor's normalized export.
                    // lastLoadedExternalDesign keeps the raw incoming form, which the normalized
                    // baseline no longer matches, so the same external design isn't reloaded when an
                    // unrelated field changes.
                    cache.lastLoadedExternalDesign = design
                    cache.lastEditorDesign = design
                    values.emailEditorRef?.editor?.loadDesign(design)
                }
            }
        }
    }),

    afterMount(({ actions, props }) => {
        if (props.value) {
            actions.resetEmailTemplate(props.value)
            autoRevealAdvancedFields(actions, props)
        }

        // Deep links and refreshes reopen the editor; urlToAction only fires on navigation
        // after mount, so the initial URL is handled here.
        if (
            props.layout !== 'inline' &&
            router.values.searchParams[EMAIL_EDITOR_URL_PARAM] === EMAIL_EDITOR_URL_VALUE
        ) {
            actions.setIsModalOpen(true)
        }

        actions.loadTemplates()
        actions.loadPersonPropertyDefinitions()
    }),

    beforeUnmount(({ props, values }) => {
        // An unmount while open (switching nodes, closing the step panel) skips the close action,
        // and the node URL sync preserves foreign search params - so strip ours here, or the next
        // email editor to mount would read the lingering param and auto-open.
        if (
            props.layout !== 'inline' &&
            values.isModalOpen &&
            router.values.searchParams[EMAIL_EDITOR_URL_PARAM] === EMAIL_EDITOR_URL_VALUE
        ) {
            const { pathname, searchParams, hashParams } = router.values.currentLocation
            const next = { ...searchParams }
            delete next[EMAIL_EDITOR_URL_PARAM]
            // A replace, not a push: teardown must not add history entries.
            router.actions.replace(pathname, next, hashParams)
        }
    }),
])

function escapeHTMLStringCurlies(htmlString: string): string {
    const parser = new DOMParser()
    const doc = parser.parseFromString(htmlString, 'text/html')

    function escapeCurlyBraces(text: string): string {
        return text.replace(/{/g, '\\{')
    }

    function processNode(node: Node): void {
        if (node.nodeType === Node.ELEMENT_NODE) {
            const element = node as HTMLElement
            if (element.tagName === 'STYLE' || element.tagName === 'SCRIPT') {
                element.textContent = escapeCurlyBraces(element.textContent || '')
            } else {
                Array.from(node.childNodes).forEach(processNode)
            }
        } else if (node.nodeType === Node.COMMENT_NODE) {
            const commentContent = (node as Comment).nodeValue || ''
            ;(node as Comment).nodeValue = escapeCurlyBraces(commentContent)
        }
    }

    processNode(doc.head)
    processNode(doc.body)

    const serializer = new XMLSerializer()
    return serializer.serializeToString(doc)
}
