import { actions, connect, kea, listeners, path, props, reducers } from 'kea'
import { EditorRef } from 'react-email-editor'

import type { emailTemplaterLogicType } from './emailTemplaterLogicType'

export type EmailTemplate = {
    design: any
    html: string
    subject?: string
    text?: string
    from?: string
    to?: string
}

export interface EmailTemplaterLogicProps {
    value?: EmailTemplate
    globals?: Record<string, any>
    onChange: (template: EmailTemplate) => void
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

            props.onChange({
                design: data.design,
                html: data.html,
            })
            actions.setIsModalOpen(false)
        },

        emailEditorReady: () => {
            if (props.template) {
                values.emailEditorRef?.editor?.loadDesign(props.template.design)
            }
        },
    })),
])
