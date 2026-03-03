import { isTextSelection } from '@tiptap/core'
import { useEditorState } from '@tiptap/react'
import { BubbleMenu } from '@tiptap/react/menus'
import { useValues } from 'kea'
import { useRef } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { richContentEditorLogic } from 'lib/components/RichContentEditor/richContentEditorLogic'
import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
import { IconBold, IconItalic, IconLink, IconOpenInNew } from 'lib/lemon-ui/icons'
import { isURL } from 'lib/utils'

import NotebookIconHeading from './NotebookIconHeading'

export const InlineMenu = ({
    extra = () => null,
}: {
    extra: (editor: RichContentEditorType) => JSX.Element | null
}): JSX.Element => {
    const { ttEditor, richContentEditor } = useValues(richContentEditorLogic)
    const menuRef = useRef<HTMLDivElement>(null)

    const { isLinkActive, href, target } = useEditorState({
        editor: ttEditor,
        selector: ({ editor }) => {
            const attrs = editor?.getAttributes('link') ?? {}
            return {
                isLinkActive: editor?.isActive('link') ?? false,
                href: attrs.href as string | undefined,
                target: attrs.target as string | undefined,
            }
        },
    })

    const setLink = (href: string): void => {
        ttEditor.commands.setMark('link', { href: href })
    }

    const openLink = (): void => {
        if (isURL(href)) {
            window.open(href, target)
        }
    }

    return (
        <BubbleMenu
            editor={ttEditor}
            shouldShow={({ editor: { isEditable }, view, state, from, to }) => {
                if (!isEditable) {
                    return false
                }

                const isChildOfMenu = menuRef.current?.contains(document.activeElement)

                // Keep menu visible while interacting with it (e.g. typing in URL input)
                if (isChildOfMenu) {
                    return true
                }

                const focused = view.hasFocus()
                const isTextBlock = isTextSelection(state.selection)

                if (!focused || !isTextBlock) {
                    return false
                }

                return state.doc.textBetween(from, to).length > 0
            }}
            options={{ placement: 'top-start' }}
        >
            <div
                ref={menuRef}
                className="NotebookInlineMenu flex bg-surface-primary rounded border items-center text-secondary p-1 gap-x-0.5"
            >
                {isLinkActive ? (
                    <>
                        <LemonInput
                            size="small"
                            placeholder="https://posthog.com"
                            onChange={setLink}
                            value={href ?? ''}
                            className="border-0"
                            autoFocus
                        />
                        <LemonButton
                            onClick={openLink}
                            icon={<IconOpenInNew />}
                            size="small"
                            disabledReason={!isURL(href) && 'Enter a URL.'}
                        />
                        <LemonButton
                            onClick={() => ttEditor.chain().focus().unsetMark('link').run()}
                            icon={<IconTrash />}
                            status="danger"
                            size="small"
                        />
                    </>
                ) : (
                    <>
                        <LemonButton
                            onClick={() => ttEditor.chain().focus().toggleHeading({ level: 1 }).run()}
                            active={ttEditor.isActive('heading', { level: 1 })}
                            icon={<NotebookIconHeading level={1} />}
                            size="small"
                        />
                        <LemonButton
                            onClick={() => ttEditor.chain().focus().toggleHeading({ level: 2 }).run()}
                            active={ttEditor.isActive('heading', { level: 2 })}
                            icon={<NotebookIconHeading level={2} />}
                            size="small"
                        />
                        <LemonButton
                            onClick={() => ttEditor.chain().focus().toggleHeading({ level: 3 }).run()}
                            active={ttEditor.isActive('heading', { level: 3 })}
                            icon={<NotebookIconHeading level={3} />}
                            size="small"
                        />
                        <LemonDivider vertical />
                        <LemonButton
                            onClick={() => ttEditor.chain().focus().toggleMark('italic').run()}
                            active={ttEditor.isActive('italic')}
                            icon={<IconItalic />}
                            size="small"
                        />
                        <LemonButton
                            onClick={() => ttEditor.chain().focus().toggleMark('bold').run()}
                            active={ttEditor.isActive('bold')}
                            icon={<IconBold />}
                            size="small"
                        />
                        <LemonButton
                            onMouseDown={(e: React.MouseEvent) => e.preventDefault()}
                            onClick={() => ttEditor.chain().focus().setMark('link').run()}
                            icon={<IconLink />}
                            size="small"
                        />
                        {extra(richContentEditor)}
                    </>
                )}
            </div>
        </BubbleMenu>
    )
}
