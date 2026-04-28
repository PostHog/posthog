import { actions, afterMount, connect, kea, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { Editor, EmailEditorProps, EditorRef as _EditorRef } from 'react-email-editor'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { objectsEqual } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { performQuery } from '~/queries/query'
import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import {
    CyclotronJobInvocationGlobals,
    FilterLogicalOperator,
    PreflightStatus,
    PropertyDefinition,
    PropertyDefinitionType,
    PropertyFilterType,
    Realm,
} from '~/types'

import { MessageTemplate } from 'products/workflows/frontend/TemplateLibrary/types'

import type { emailTemplaterLogicType } from './emailTemplaterLogicType'
import type { EmailTemplate } from './types'
import { renderWysiwygToHtml } from './wysiwygRender'

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

export type EmailContentTab = 'visual' | 'plaintext' | 'wysiwyg'

export type WysiwygRecentEvent = {
    event: string
    timestamp: string
    properties: Record<string, any>
    person?: { id: string; properties: Record<string, any>; name: string }
}

const DEFAULT_WYSIWYG_PREVIEW_WIDTH: number = 480

const DEFAULT_WYSIWYG_SOURCE = `<!-- Edit raw HTML or react.email JSX (e.g. <Html>, <Container>, <Text>). -->
<!-- Liquid tokens like {{ event.properties.foo }} render with the event you pick above. -->
<div style="font-family: sans-serif; padding: 24px;">
  <h1>Hi {{ person.properties.email }} 👋</h1>
  <p>Thanks for triggering <strong>{{ event.event }}</strong>.</p>
</div>
`

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
        values: [preflightLogic, ['preflight']],
    })),
    actions({
        setEmailEditorRef: (emailEditorRef: EditorRef | null) => ({ emailEditorRef }),
        onEmailEditorReady: true,
        setIsModalOpen: (isModalOpen: boolean) => ({ isModalOpen }),
        setIsSaveTemplateModalOpen: (isOpen: boolean) => ({ isOpen }),
        applyTemplate: (template: MessageTemplate) => ({ template }),
        closeWithConfirmation: true,
        setTemplatingEngine: (templating: 'hog' | 'liquid') => ({ templating }),
        saveAsTemplate: (name: string, description: string) => ({ name, description }),
        setActiveContentTab: (tab: EmailContentTab) => ({ tab }),
        revealAdvancedField: (key: EmailMetaFieldKey) => ({ key }),
        hideAdvancedField: (key: EmailMetaFieldKey) => ({ key }),
        setWysiwygPreviewHtml: (html: string) => ({ html }),
        setWysiwygPreviewError: (error: string | null) => ({ error }),
        setWysiwygSelectedEvent: (eventName: string) => ({ eventName }),
        setWysiwygPreviewWidth: (width: number) => ({ width }),
        setWysiwygSampleGlobals: (globals: CyclotronJobInvocationGlobals | null) => ({ globals }),
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
            'visual' as EmailContentTab,
            {
                setActiveContentTab: (_, { tab }) => tab,
                applyTemplate: (_, { template }) => {
                    const hasWysiwyg = !!template.content.email.wysiwygSource
                    if (hasWysiwyg) {
                        return 'wysiwyg'
                    }
                    const hasHtml = !!template.content.email.html
                    return hasHtml ? 'visual' : 'plaintext'
                },
            },
        ],
        wysiwygPreviewHtml: [
            '' as string,
            {
                setWysiwygPreviewHtml: (_, { html }) => html,
            },
        ],
        wysiwygPreviewError: [
            null as string | null,
            {
                setWysiwygPreviewError: (_, { error }) => error,
            },
        ],
        wysiwygSelectedEvent: [
            '' as string,
            {
                setWysiwygSelectedEvent: (_, { eventName }) => eventName,
            },
        ],
        wysiwygPreviewWidth: [
            DEFAULT_WYSIWYG_PREVIEW_WIDTH,
            {
                setWysiwygPreviewWidth: (_, { width }) => Math.max(200, width),
            },
        ],
        wysiwygSampleGlobals: [
            null as CyclotronJobInvocationGlobals | null,
            {
                setWysiwygSampleGlobals: (_, { globals }) => globals,
            },
        ],
    }),

    loaders(({ actions, values }) => ({
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
        wysiwygRecentEvents: [
            [] as WysiwygRecentEvent[],
            {
                loadWysiwygRecentEvents: async (payload?: { eventName?: string }) => {
                    const eventName = payload?.eventName
                    const query: EventsQuery = {
                        kind: NodeKind.EventsQuery,
                        select: ['*', 'person'],
                        after: '-7d',
                        limit: 10,
                        orderBy: ['timestamp DESC'],
                        modifiers: {
                            personsOnEventsMode: 'person_id_no_override_properties_on_events',
                        },
                    }
                    if (eventName) {
                        query.fixedProperties = [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        type: PropertyFilterType.HogQL,
                                        key: hogql`event = ${eventName}`,
                                    },
                                ],
                            },
                        ]
                    }

                    const response = await performQuery(query)
                    const results = (response?.results ?? []) as Array<[any, any]>
                    const matched = results.map(([event, person]) => ({
                        event: event.event,
                        timestamp: event.timestamp,
                        properties: event.properties || {},
                        person: person
                            ? {
                                  id: person.id,
                                  properties: person.properties,
                                  name: person.name || 'Unknown person',
                              }
                            : undefined,
                    }))

                    if (matched.length > 0 && !values.wysiwygSampleGlobals) {
                        const first = matched[0]
                        actions.setWysiwygSampleGlobals({
                            event: {
                                uuid: '',
                                distinct_id: '',
                                timestamp: first.timestamp,
                                elements_chain: '',
                                url: '',
                                event: first.event,
                                properties: first.properties,
                            },
                            person: first.person,
                            groups: {},
                            project: { id: 0, name: '', url: '' },
                            source: { name: '', url: '' },
                        } as CyclotronJobInvocationGlobals)
                    }

                    return matched
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

                if (values.activeContentTab === 'wysiwyg') {
                    const source = formValues.wysiwygSource ?? ''
                    try {
                        const renderedHtml = await renderWysiwygToHtml(source)
                        const finalValues: EmailTemplate = {
                            ...formValues,
                            html: ['native_email', 'native_email_template'].includes(props.type)
                                ? renderedHtml
                                : escapeHTMLStringCurlies(renderedHtml),
                            wysiwygSource: source,
                        }
                        props.onChange(finalValues)
                        actions.setIsModalOpen(false)
                    } catch (err: any) {
                        lemonToast.error(`Failed to render WYSIWYG email: ${err?.message ?? err}`)
                    }
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
            if (props.value?.design) {
                values.emailEditorRef?.editor?.loadDesign(props.value.design)
            }
        },

        setEmailTemplateValue: ({ name, value }) => {
            const key = Array.isArray(name) ? name[0] : name

            if (key === 'wysiwygSource') {
                void renderWysiwygPreview(actions, values, value as string)
            }

            if (values.isModalOpen) {
                // When open we only update on save
                return
            }

            if (name === 'html') {
                return
            }

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
                if (props.value.wysiwygSource) {
                    actions.setActiveContentTab('wysiwyg')
                } else {
                    const hasHtml = !!props.value.html
                    actions.setActiveContentTab(hasHtml ? 'visual' : 'plaintext')
                }
            }
        },

        setActiveContentTab: ({ tab }) => {
            if (tab === 'wysiwyg') {
                if (values.wysiwygRecentEvents.length === 0) {
                    actions.loadWysiwygRecentEvents({})
                }
                if (!values.emailTemplate?.wysiwygSource) {
                    actions.setEmailTemplateValue('wysiwygSource', DEFAULT_WYSIWYG_SOURCE)
                } else {
                    void renderWysiwygPreview(actions, values)
                }
            }
        },

        setWysiwygSelectedEvent: ({ eventName }) => {
            if (eventName) {
                actions.loadWysiwygRecentEvents({ eventName })
            }
        },

        loadWysiwygRecentEventsSuccess: () => {
            // Once events arrive, re-render the preview using the freshly-set globals.
            actions.setEmailTemplateValue('wysiwygSource', values.emailTemplate?.wysiwygSource ?? '')
        },

        setWysiwygSampleGlobals: () => {
            void renderWysiwygPreview(actions, values)
        },

        applyTemplate: ({ template }) => {
            const emailTemplateContent = template.content.email
            actions.setEmailTemplateValues(emailTemplateContent)

            // Load the design into the editor if it's ready and has a design
            if (values.isEmailEditorReady && emailTemplateContent.design) {
                values.emailEditorRef?.editor?.loadDesign(emailTemplateContent.design)
            }
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
                } else if (values.activeContentTab === 'wysiwyg') {
                    const source = currentValues?.wysiwygSource ?? ''
                    const renderedHtml = await renderWysiwygToHtml(source)
                    emailContent = {
                        ...currentValues,
                        html: ['native_email', 'native_email_template'].includes(props.type)
                            ? renderedHtml
                            : escapeHTMLStringCurlies(renderedHtml),
                        wysiwygSource: source,
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

    propsChanged(({ actions, props }, oldProps) => {
        if (props.value && !objectsEqual(props.value, oldProps.value)) {
            actions.resetEmailTemplate(props.value)
            autoRevealAdvancedFields(actions, props)
        }
    }),

    afterMount(({ actions, props, values }) => {
        if (props.value) {
            actions.resetEmailTemplate(props.value)
            autoRevealAdvancedFields(actions, props)
            if (props.value.wysiwygSource) {
                actions.setActiveContentTab('wysiwyg')
            }
        }

        actions.loadTemplates()
        actions.loadPersonPropertyDefinitions()

        if (values.activeContentTab === 'wysiwyg') {
            actions.loadWysiwygRecentEvents({})
        }
    }),
])

async function renderWysiwygPreview(
    actions: Record<string, any>,
    values: Record<string, any>,
    sourceOverride?: string
): Promise<void> {
    const source = sourceOverride ?? values.emailTemplate?.wysiwygSource ?? ''
    if (!source) {
        actions.setWysiwygPreviewHtml('')
        actions.setWysiwygPreviewError(null)
        return
    }
    try {
        const globals = values.wysiwygSampleGlobals ? { ...values.wysiwygSampleGlobals } : {}
        const html = await renderWysiwygToHtml(source, globals)
        actions.setWysiwygPreviewHtml(html)
        actions.setWysiwygPreviewError(null)
    } catch (err: any) {
        actions.setWysiwygPreviewError(err?.message ?? String(err))
    }
}

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
