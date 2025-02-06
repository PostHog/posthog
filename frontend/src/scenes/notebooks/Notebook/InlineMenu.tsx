import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'
import { Editor, isTextSelection } from '@tiptap/core'
import { BubbleMenu } from '@tiptap/react'
import { useActions } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconBold, IconComment, IconItalic, IconLink, IconOpenInNew } from 'lib/lemon-ui/icons'
import { isURL, uuid } from 'lib/utils'
import { useRef } from 'react'

import NotebookIconHeading from './NotebookIconHeading'
import { notebookLogic } from './notebookLogic'

export const InlineMenu = ({ editor }: { editor: Editor }): JSX.Element => {
    const { insertComment } = useActions(notebookLogic)
    const { href, target } = editor.getAttributes('link')
    const menuRef = useRef<HTMLDivElement>(null)
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')
    const commentSelected = editor.isActive('comment')

    const setLink = (href: string): void => {
        editor.commands.setMark('link', { href: href })
    }

    const openLink = (): void => {
        window.open(href, target)
    }

    return (
        <BubbleMenu
            editor={editor}
            shouldShow={({ editor: { isEditable }, view, state, from, to }) => {
                const isChildOfMenu = menuRef.current?.contains(document.activeElement)
                const focused = view.hasFocus() || isChildOfMenu
                const isTextBlock = isTextSelection(state.selection)

                if (!focused || !isEditable || !isTextBlock) {
                    return false
                }

                return state.doc.textBetween(from, to).length > 0
            }}
        >
            <div
                ref={menuRef}
                className="NotebookInlineMenu flex bg-bg-light rounded border items-center text-muted-alt p-1 space-x-0.5"
            >
                {editor.isActive('link') ? (
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
                            onClick={() => editor.chain().focus().unsetMark('link').run()}
                            icon={<IconTrash />}
                            status="danger"
                            size="small"
                        />
                    </>
                ) : (
                    <>
                        <LemonButton
                            onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
                            active={editor.isActive('heading', { level: 1 })}
                            icon={<NotebookIconHeading level={1} />}
                            size="small"
                        />
                        <LemonButton
                            onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
                            active={editor.isActive('heading', { level: 2 })}
                            icon={<NotebookIconHeading level={2} />}
                            size="small"
                        />
                        <LemonButton
                            onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
                            active={editor.isActive('heading', { level: 3 })}
                            icon={<NotebookIconHeading level={3} />}
                            size="small"
                        />
                        <LemonDivider vertical />
                        <LemonButton
                            onClick={() => editor.chain().focus().toggleMark('italic').run()}
                            active={editor.isActive('italic')}
                            icon={<IconItalic />}
                            size="small"
                        />
                        <LemonButton
                            onClick={() => editor.chain().focus().toggleMark('bold').run()}
                            active={editor.isActive('bold')}
                            icon={<IconBold />}
                            size="small"
                        />
                        <LemonButton
                            onClick={() => editor.chain().focus().setMark('link').run()}
                            icon={<IconLink />}
                            size="small"
                        />
                    </>
                )}
                {hasDiscussions && !commentSelected && (
                    <>
                        <LemonDivider vertical />
                        <LemonButton
                            onClick={() => {
                                const markId = uuid()
                                editor.commands.setMark('comment', { id: markId })
                                insertComment({ type: 'mark', id: markId })
                            }}
                            icon={<IconComment className="w-4 h-4" />}
                            size="small"
                        />
                    </>
                )}
            </div>
        </BubbleMenu>
    )
}
