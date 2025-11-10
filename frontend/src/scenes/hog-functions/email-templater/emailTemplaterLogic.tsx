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
        setInitialState: (initialState: EmailTemplate | null) => ({ initialState }),
        setEditorModified: (modified: boolean) => ({ modified }),
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
        initialState: [
            null as EmailTemplate | null,
            {
                setInitialState: (_, { initialState }) => initialState,
                // Don't clear on modal close - keep the truly initial state
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
                setIsModalOpen: (state, { isModalOpen }) => {
                    // Clear applied template when closing modal
                    return isModalOpen ? state : null
                },
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
        editorModified: [
            false,
            {
                setEditorModified: (_, { modified }) => modified,
                setIsModalOpen: (state, { isModalOpen }) => {
                    // Reset when modal closes
                    return isModalOpen ? state : false
                },
                applyTemplate: () => false, // Reset when applying template
                submitEmailTemplate: () => false, // Reset after saving
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
            const design = values.initialState?.design || props.defaultValue?.design || props.value?.design
            if (design) {
                values.emailEditorRef?.editor?.loadDesign(design)
            }

            // Register change listener on the editor
            if (values.emailEditorRef?.editor) {
                const editor = values.emailEditorRef.editor

                // Listen for design updates to track modifications
                ;(editor as any).addEventListener?.('design:updated', () => {
                    // Only mark as modified if modal is open and editor is ready
                    if (values.isModalOpen && values.isEmailEditorReady) {
                        actions.setEditorModified(true)
                    }
                })
            }
        },

        resetEmailTemplate: () => {
            // When resetting the form, also reload the editor design
            if (values.emailEditorRef?.editor && values.isEmailEditorReady) {
                const design = values.initialState?.design || props.defaultValue?.design || props.value?.design
                if (design) {
                    values.emailEditorRef.editor.loadDesign(design)
                } else {
                    values.emailEditorRef.editor.loadBlank()
                }
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
            // Don't propagate changes to parent when modal is open
            // Changes should only be saved when user clicks Save
            if (!values.isModalOpen) {
                props.onChange({
                    ...props.value,
                    ...values,
                } as EmailTemplate)
            }
        },

        applyTemplate: ({ template }) => {
            const emailTemplateContent = template.content.email

            // When modal is open, don't update HTML field (it will be generated on save)
            // Only update the other fields and load the design into the editor
            if (values.isModalOpen) {
                const { html, design, text, ...otherFields } = emailTemplateContent
                actions.setEmailTemplateValues(otherFields)

                // Load the design into the editor if it's ready and has a design
                if (values.isEmailEditorReady && design) {
                    values.emailEditorRef?.editor?.loadDesign(design)
                }
            } else {
                // If modal is closed, update all fields
                actions.setEmailTemplateValues(emailTemplateContent)

                // Load the design into the editor if it's ready and has a design
                if (values.isEmailEditorReady && emailTemplateContent.design) {
                    values.emailEditorRef?.editor?.loadDesign(emailTemplateContent.design)
                }
            }
        },

        closeWithConfirmation: () => {
            // Check both form changes and editor modifications
            if (values.emailTemplateChanged || values.editorModified) {
                LemonDialog.open({
                    title: 'Discard changes',
                    description: 'Are you sure you want to discard your changes?',
                    primaryButton: {
                        onClick: () => {
                            // Reset to initial state that was captured when component mounted
                            actions.resetEmailTemplate(values.initialState ?? props.defaultValue ?? undefined)
                            // Also reload the editor with the original design
                            if (values.emailEditorRef?.editor) {
                                const originalDesign =
                                    values.initialState?.design || props.defaultValue?.design || props.value?.design
                                if (originalDesign) {
                                    values.emailEditorRef.editor.loadDesign(originalDesign)
                                } else {
                                    values.emailEditorRef.editor.loadBlank()
                                }
                            }
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
        if (props.defaultValue && !objectsEqual(props.defaultValue, oldProps.defaultValue)) {
            actions.resetEmailTemplate(props.defaultValue)
        }
    }),

    afterMount(({ actions, props }) => {
        // Capture the truly initial state on mount
        const initialState = props.defaultValue || props.value || null
        actions.setInitialState(initialState)

        if (initialState) {
            actions.resetEmailTemplate(initialState)
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
