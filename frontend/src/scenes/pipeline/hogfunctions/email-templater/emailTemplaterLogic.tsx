import { actions, connect, kea, listeners, LogicWrapper, path, props, reducers } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import { EditorRef as _EditorRef } from 'react-email-editor'

import type { emailTemplaterLogicType } from './emailTemplaterLogicType'

// Helping kea-typegen navigate the exported type
export interface EditorRef extends _EditorRef {}

export type EmailTemplate = {
    design: any
    html: string
    subject: string
    text: string
    from: string
    to: string
}

export interface EmailTemplaterLogicProps {
    formLogic: LogicWrapper
    formLogicProps: any
    formKey: string
    formFieldsPrefix?: string
    globals?: Record<string, any>
}

export const emailTemplaterLogic = kea<emailTemplaterLogicType>([
    props({} as EmailTemplaterLogicProps),
    connect({
        // values: [teamLogic, ['currentTeam'], groupsModel, ['groupTypes'], userLogic, ['hasAvailableFeature']],
    }),
    path(() => ['scenes', 'pipeline', 'hogfunctions', 'emailTemplaterLogic']),
    actions({
        onSave: true,
        setEmailEditorRef: (emailEditorRef: EditorRef | null) => ({ emailEditorRef }),
        emailEditorReady: true,
        setIsModalOpen: (isModalOpen: boolean) => ({ isModalOpen }),
    }),
    reducers({
        emailEditorRef: [
            null as EditorRef | null,
            {
                setEmailEditorRef: (_, { emailEditorRef }) => emailEditorRef,
            },
        ],
        isModalOpen: [
            false,
            {
                setIsModalOpen: (_, { isModalOpen }) => isModalOpen,
            },
        ],
    }),

    listeners(({ props, values, actions }) => ({
        onSave: async () => {
            const editor = values.emailEditorRef?.editor
            if (!editor) {
                return
            }
            const data = await new Promise<any>((res) => editor.exportHtml(res))

            // TRICKY: We have to build the action we need in order to nicely callback to the form field
            const setFormValue = props.formLogic.findMounted(props.formLogicProps)?.actions?.[
                `set${capitalizeFirstLetter(props.formKey)}Value`
            ]

            const pathParts = props.formFieldsPrefix ? props.formFieldsPrefix.split('.') : []

            setFormValue(pathParts.concat('design'), data.design)
            setFormValue(pathParts.concat('html'), escapeHTMLStringCurlies(data.html))

            // Load the logic and set the property...
            actions.setIsModalOpen(false)
        },

        emailEditorReady: () => {
            const pathParts = (props.formFieldsPrefix ? props.formFieldsPrefix.split('.') : []).concat('design')

            let value = props.formLogic.findMounted(props.formLogicProps)?.values?.[props.formKey]

            // Get the value from the form and set it in the editor
            while (pathParts.length && value) {
                value = value[pathParts.shift()!]
            }

            if (value) {
                values.emailEditorRef?.editor?.loadDesign(value)
            }
        },
    })),
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
