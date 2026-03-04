import './FormEditor.scss'

import { Extension, JSONContent } from '@tiptap/core'
import ExtensionDocument from '@tiptap/extension-document'
import { Image } from '@tiptap/extension-image'
import { TextAlign } from '@tiptap/extension-text-align'
import { Placeholder } from '@tiptap/extensions'
import { Node as ProseMirrorNode } from '@tiptap/pm/model'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { forwardRef, useEffect, useImperativeHandle } from 'react'
import { createRoot, Root } from 'react-dom/client'

import { IconImage, IconLogomark } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FormDragFeedback } from './FormDragFeedback'
import { FormDragHandle } from './FormDragHandle'
import { FormButtonNode } from './nodes/FormButtonNode'
import { FormPageBreakNode } from './nodes/FormPageBreakNode'
import { FormQuestionNode } from './nodes/FormQuestionNode'
import { FormThankYouBreakNode } from './nodes/FormThankYouBreakNode'
import { SlashCommandExtension } from './SlashCommands'

const FormDocument = ExtensionDocument.extend({
    content: 'heading block*',
})

const TitleGuard = Extension.create({
    name: 'titleGuard',
    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey('titleGuard'),
                props: {
                    handleDrop(view, event) {
                        if (view.dom.classList.contains('dragging')) {
                            return false
                        }

                        const coords = { left: event.clientX, top: event.clientY }
                        const pos = view.posAtCoords(coords)
                        if (!pos) {
                            return false
                        }
                        const titleEnd = view.state.doc.firstChild?.nodeSize ?? 0
                        return pos.pos < titleEnd
                    },
                },
            }),
        ]
    },
})

const titleActionsKey = new PluginKey<{ showLogo: boolean; showCover: boolean }>('titleActions')

const TitleActions = Extension.create({
    name: 'titleActions',
    addOptions() {
        return {
            onAddLogo: undefined as (() => void) | undefined,
            onAddCover: undefined as (() => void) | undefined,
        }
    },
    addProseMirrorPlugins() {
        const { onAddLogo, onAddCover } = this.options
        return [
            new Plugin({
                key: titleActionsKey,
                state: {
                    init() {
                        return { showLogo: false, showCover: false }
                    },
                    apply(tr, prev) {
                        return tr.getMeta(titleActionsKey) ?? prev
                    },
                },
                props: {
                    decorations(state) {
                        const { doc } = state
                        const pluginState = titleActionsKey.getState(state)
                        const logoVisible = pluginState?.showLogo ?? false
                        const coverVisible = pluginState?.showCover ?? false

                        if (logoVisible && coverVisible) {
                            return DecorationSet.empty
                        }

                        let hasBodyContent = false
                        for (let i = 1; i < doc.childCount; i++) {
                            const node = doc.child(i)
                            if (node.type.name === 'formButton') {
                                continue
                            }
                            if (
                                node.type.name === 'paragraph' &&
                                node.textContent.trim().length === 0 &&
                                node.childCount === 0
                            ) {
                                continue
                            }
                            hasBodyContent = true
                            break
                        }
                        const hasContent = hasBodyContent || (doc.firstChild?.textContent.trim().length ?? 0) > 0
                        let activeRoot: Root | null = null
                        const widget = Decoration.widget(
                            1,
                            () => {
                                const el = document.createElement('div')
                                el.className = `FormEditor__title-actions${hasContent ? '' : ' FormEditor__title-actions--no-content'}`
                                el.contentEditable = 'false'
                                activeRoot = createRoot(el)
                                activeRoot.render(
                                    <>
                                        {!logoVisible && (
                                            <LemonButton
                                                type="tertiary"
                                                size="xsmall"
                                                icon={<IconLogomark />}
                                                onClick={onAddLogo}
                                            >
                                                Add logo
                                            </LemonButton>
                                        )}
                                        {!coverVisible && (
                                            <LemonButton
                                                type="tertiary"
                                                size="xsmall"
                                                icon={<IconImage />}
                                                onClick={onAddCover}
                                            >
                                                Add cover
                                            </LemonButton>
                                        )}
                                    </>
                                )
                                return el
                            },
                            {
                                side: -1,
                                key: `title-actions-${hasContent ? 'active' : 'hidden'}-${logoVisible}-${coverVisible}`,
                                destroy: () => {
                                    activeRoot?.unmount()
                                    activeRoot = null
                                },
                            }
                        )
                        return DecorationSet.create(doc, [widget])
                    },
                },
            }),
        ]
    },
})

export interface FormEditorHandle {
    insertEmptyParagraph: () => void
    setContent: (content: JSONContent) => void
}

export interface FormEditorProps {
    content?: JSONContent | null
    onUpdate?: (content: JSONContent) => void
    onAddLogo?: () => void
    onAddCover?: () => void
    showLogo?: boolean
    showCover?: boolean
    submitButtonText?: string
    onSubmitButtonTextChange?: (text: string) => void
}

const DEFAULT_CONTENT: JSONContent = {
    type: 'doc',
    content: [{ type: 'heading', attrs: { level: 1 } }],
}

export const FormEditor = forwardRef<FormEditorHandle, FormEditorProps>(function FormEditor(
    {
        content,
        onUpdate,
        onAddLogo,
        onAddCover,
        showLogo = false,
        showCover = false,
        submitButtonText = 'Submit',
        onSubmitButtonTextChange,
    },
    ref
) {
    const editor = useEditor({
        extensions: [
            FormDocument,
            StarterKit.configure({
                document: false,
                heading: {
                    levels: [1, 2, 3],
                },
                codeBlock: false,
                dropcursor: false,
                gapcursor: false,
                trailingNode: {
                    node: 'paragraph',
                    notAfter: ['heading', 'formButton'],
                },
            }),
            TextAlign.configure({
                types: ['heading', 'paragraph'],
            }),
            Image.configure({
                HTMLAttributes: { class: 'form-content-image' },
                allowBase64: true,
            }),
            Placeholder.configure({
                showOnlyCurrent: false,
                placeholder: ({ node, pos, hasAnchor }: { node: ProseMirrorNode; pos: number; hasAnchor: boolean }) => {
                    if (node.type.name === 'heading' && pos === 0) {
                        return 'Form title'
                    }
                    if (!hasAnchor) {
                        return ''
                    }
                    if (node.type.name === 'heading') {
                        return `Heading ${node.attrs.level}`
                    }
                    return "Type '/' to add blocks"
                },
            }),
            FormQuestionNode,
            FormButtonNode.configure({
                submitButtonText,
                onSubmitButtonTextChange,
            }),
            FormPageBreakNode,
            FormThankYouBreakNode,
            SlashCommandExtension,
            FormDragFeedback,
            TitleGuard,
            TitleActions.configure({ onAddLogo, onAddCover }),
        ],
        content: content || DEFAULT_CONTENT,
        onUpdate: ({ editor: e }) => {
            onUpdate?.(e.getJSON())
        },
    })

    useEffect(() => {
        if (editor) {
            editor.view.dispatch(editor.state.tr.setMeta(titleActionsKey, { showLogo, showCover }))
        }
    }, [showLogo, showCover, editor])

    useImperativeHandle(
        ref,
        () => ({
            insertEmptyParagraph() {
                if (!editor) {
                    return
                }
                const headingSize = editor.state.doc.firstChild?.nodeSize ?? 2
                editor.chain().insertContentAt(headingSize, { type: 'paragraph' }).focus('end').run()
            },
            setContent(newContent: JSONContent) {
                if (!editor) {
                    return
                }
                editor.commands.setContent(newContent)
            },
        }),
        [editor]
    )

    return (
        <div className="FormEditor">
            <EditorContent editor={editor} className="FormEditor__content" />
            <FormDragHandle editor={editor} />
        </div>
    )
})
