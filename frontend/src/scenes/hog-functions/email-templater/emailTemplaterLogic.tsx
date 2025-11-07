import { actions, afterMount, connect, kea, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { Editor, EmailEditorProps, EditorRef as _EditorRef } from 'react-email-editor'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { objectsEqual } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { PreflightStatus, PropertyDefinition, PropertyDefinitionType, Realm } from '~/types'

import { MessageTemplate } from 'products/workflows/frontend/TemplateLibrary/messageTemplatesLogic'

import { EmailTemplaterType } from './EmailTemplater'
import type { emailTemplaterLogicType } from './emailTemplaterLogicType'

export type UnlayerMergeTags = NonNullable<EmailEditorProps['options']>['mergeTags']

// Helping kea-typegen navigate the exported type
export interface EditorRef extends _EditorRef {}

type JSONTemplate = Parameters<Editor['loadDesign']>[0]

export type EmailTemplate = {
    design: JSONTemplate | null
    html: string
    subject: string
    text: string
    from: string
    to: string
}

export interface EmailTemplaterLogicProps {
    value: EmailTemplate | null
    onChange: (value: EmailTemplate) => void
    variables?: Record<string, any>
    type: EmailTemplaterType
    defaultValue?: EmailTemplate | null
    templating?: boolean | 'hog' | 'liquid'
    onChangeTemplating?: (templating: 'hog' | 'liquid') => void
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
    }),

    forms(({ actions, values, props }) => ({
        emailTemplate: {
            defaults: props.defaultValue as EmailTemplate,
            submit: async (formValues: EmailTemplate | undefined) => {
                if (!formValues) {
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
                    html: escapeHTMLStringCurlies(htmlData.html),
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
            const editor = values.emailEditorRef?.editor
            if (!editor || !values.isEmailEditorReady) {
                lemonToast.error('Editor not ready')
                return
            }

            try {
                const [htmlData, textData]: [{ html: string; design: JSONTemplate }, { text: string }] =
                    await Promise.all([
                        new Promise<any>((res) => editor.exportHtml(res)),
                        new Promise<any>((res) => editor.exportPlainText(res)),
                    ])

                const currentValues = values.emailTemplate

                const templateData: Partial<MessageTemplate> = {
                    name,
                    description,
                    content: {
                        templating: values.templatingEngine,
                        email: {
                            ...currentValues,
                            html: escapeHTMLStringCurlies(htmlData.html),
                            text: textData.text,
                            design: htmlData.design,
                        },
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
        }
    }),

    afterMount(({ actions, props }) => {
        if (props.value) {
            actions.resetEmailTemplate(props.value)
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
