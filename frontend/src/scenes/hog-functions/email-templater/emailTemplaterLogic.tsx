import { actions, afterMount, connect, kea, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { Editor, EmailEditorProps, EditorRef as _EditorRef } from 'react-email-editor'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { PreflightStatus, PropertyDefinition, PropertyDefinitionType, Realm } from '~/types'

import { MessageTemplate } from 'products/workflows/frontend/TemplateLibrary/types'

import type { emailTemplaterLogicType } from './emailTemplaterLogicType'
import type { ReactEmailEditorShimRef } from './react-email/ReactEmailEditorShim'
import { isReactEmailDesign, isUnlayerDesign } from './react-email/types'
import type { EmailTemplate } from './types'

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
 * Unified handle covering both the Unlayer `EditorRef` and our react-email
 * shim. Both expose an `editor` with the three methods `emailTemplaterLogic`
 * actually calls: `loadDesign`, `exportHtml`, `exportPlainText`.
 */
export type EmailEditorHandle = EditorRef | ReactEmailEditorShimRef | null

export interface EmailTemplaterLogicProps {
    value: EmailTemplate | null
    onChange: (value: EmailTemplate) => void
    variables?: Record<string, any>
    type: EmailTemplaterType
    defaultValue?: EmailTemplate | null
    templating?: boolean | 'hog' | 'liquid'
    onChangeTemplating?: (templating: 'hog' | 'liquid') => void
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

export const emailTemplaterLogic = kea<emailTemplaterLogicType>([
    props({} as EmailTemplaterLogicProps),
    path(['scenes', 'hog-functions', 'email-templater', 'emailTemplaterLogic']),
    connect(() => ({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setEmailEditorRef: (emailEditorRef: EmailEditorHandle) => ({ emailEditorRef }),
        onEmailEditorReady: true,
        setIsModalOpen: (isModalOpen: boolean) => ({ isModalOpen }),
        setIsSaveTemplateModalOpen: (isOpen: boolean) => ({ isOpen }),
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
            null as EmailEditorHandle,
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
        /**
         * Picks the editor engine for the current template:
         * - always Unlayer when the flag is off (opt-in rollout),
         * - always Unlayer when the existing design is an Unlayer shape so we
         *   never orphan previously saved templates,
         * - react-email otherwise (new blank templates or designs already saved
         *   as TipTap JSONContent).
         */
        useReactEmailEditor: [
            (s) => [s.featureFlags, (_, props: EmailTemplaterLogicProps) => props.value],
            (featureFlags: Record<string, boolean | string>, value: EmailTemplate | null): boolean => {
                if (!featureFlags[FEATURE_FLAGS.EMAIL_TEMPLATER_REACT_EMAIL]) {
                    return false
                }
                if (value?.design && isUnlayerDesign(value.design)) {
                    return false
                }
                return !value?.design || isReactEmailDesign(value.design)
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

    forms(({ actions, values, props }) => ({
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

                // Both Unlayer's `EditorRef.editor` and our react-email shim
                // expose `exportHtml(cb)` + `exportPlainText(cb)` with the same
                // callback shape, so the polymorphism is safe here.
                const [htmlData, textData]: [{ html: string; design: JSONTemplate }, { text: string }] =
                    await Promise.all([
                        new Promise<any>((res) => (editor as any).exportHtml(res)),
                        new Promise<any>((res) => (editor as any).exportPlainText(res)),
                    ])

                const finalValues: EmailTemplate = {
                    ...formValues,
                    html: ['native_email', 'native_email_template'].includes(props.type)
                        ? htmlData.html
                        : escapeHTMLStringCurlies(htmlData.html),
                    text: textData.text,
                    design: htmlData.design,
                }

                props.onChange(finalValues)
                actions.setIsModalOpen(false)
            },
        },
    })),

    listeners(({ props, values, actions }) => ({
        onEmailEditorReady: () => {
            const design = props.value?.design
            if (!design) {
                return
            }
            // Only hand the design to the active editor engine — mismatched
            // shapes would crash either loader.
            if (values.useReactEmailEditor && !isReactEmailDesign(design)) {
                return
            }
            if (!values.useReactEmailEditor && !isUnlayerDesign(design)) {
                return
            }
            ;(values.emailEditorRef as EmailEditorHandle)?.editor?.loadDesign(design as any)
        },

        setEmailTemplateValue: ({ name, value }) => {
            if (values.isModalOpen) {
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
                const hasHtml = !!props.value.html
                actions.setActiveContentTab(hasHtml ? 'visual' : 'plaintext')
            }
        },

        applyTemplate: ({ template }) => {
            const emailTemplateContent = template.content.email
            actions.setEmailTemplateValues(emailTemplateContent)

            // Load the design into the editor if it's ready and has a design
            const design = emailTemplateContent.design
            if (!values.isEmailEditorReady || !design) {
                return
            }
            if (values.useReactEmailEditor && !isReactEmailDesign(design)) {
                return
            }
            if (!values.useReactEmailEditor && !isUnlayerDesign(design)) {
                return
            }
            ;(values.emailEditorRef as EmailEditorHandle)?.editor?.loadDesign(design as any)
        },

        closeWithConfirmation: () => {
            if (values.emailTemplateChanged) {
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
            } else {
                actions.setIsModalOpen(false)
            }
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
                            new Promise<any>((res) => (editor as any).exportHtml(res)),
                            new Promise<any>((res) => (editor as any).exportPlainText(res)),
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

    propsChanged(({ actions, props }, oldProps) => {
        if (props.value && !objectsEqual(props.value, oldProps.value)) {
            actions.resetEmailTemplate(props.value)
            autoRevealAdvancedFields(actions, props)
        }
    }),

    afterMount(({ actions, props }) => {
        if (props.value) {
            actions.resetEmailTemplate(props.value)
            autoRevealAdvancedFields(actions, props)
        }

        actions.loadTemplates()
        actions.loadPersonPropertyDefinitions()
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
