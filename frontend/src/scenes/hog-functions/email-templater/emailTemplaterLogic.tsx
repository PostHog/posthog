import { LemonDialog } from '@posthog/lemon-ui'
import { actions, afterMount, kea, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { objectsEqual } from 'lib/utils'
import { MessageTemplate } from 'products/messaging/frontend/TemplateLibrary/messageTemplatesLogic'
import { Editor, EditorRef as _EditorRef, EmailEditorProps } from 'react-email-editor'

import { PropertyDefinition, PropertyDefinitionType } from '~/types'

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
    emailMetaFields?: ('from' | 'to' | 'subject')[]
}

export const emailTemplaterLogic = kea<emailTemplaterLogicType>([
    props({} as EmailTemplaterLogicProps),
    path(['scenes', 'hog-functions', 'email-templater', 'emailTemplaterLogic']),
    actions({
        setEmailEditorRef: (emailEditorRef: EditorRef | null) => ({ emailEditorRef }),
        onEmailEditorReady: true,
        setIsModalOpen: (isModalOpen: boolean) => ({ isModalOpen }),
        applyTemplate: (template: MessageTemplate) => ({ template }),
        closeWithConfirmation: true,
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
        appliedTemplate: [
            null as MessageTemplate | null,
            {
                applyTemplate: (_, { template }) => template,
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
        logicProps: [() => [(_, props) => props], (props): EmailTemplaterLogicProps => props],
        mergeTags: [
            (s) => [s.personPropertyDefinitions],
            (personPropertyDefinitions: PropertyDefinition[]): UnlayerMergeTags => {
                const tags: UnlayerMergeTags = {}

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
    }),

    forms(({ actions, values, props }) => ({
        emailTemplate: {
            defaults: {
                from: '',
                subject: '',
                to: '',
                html: '',
                design: null as object | null,
                text: '',
            } as EmailTemplate,
            submit: async (value) => {
                const editor = values.emailEditorRef?.editor
                if (!editor || !values.isEmailEditorReady) {
                    return
                }
                const [htmlData, textData] = await Promise.all([
                    new Promise<any>((res) => editor.exportHtml(res)),
                    new Promise<any>((res) => editor.exportPlainText(res)),
                ])

                const finalValues = {
                    ...value,
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

        applyTemplate: ({ template }) => {
            const emailTemplateContent = template.content.email
            actions.setEmailTemplateValues(emailTemplateContent)
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
