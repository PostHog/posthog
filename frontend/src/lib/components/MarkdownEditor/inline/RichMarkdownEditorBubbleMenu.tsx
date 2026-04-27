import { Editor, isTextSelection } from '@tiptap/core'
import type { EditorState } from '@tiptap/pm/state'
import { BubbleMenu } from '@tiptap/react/menus'
import { useCallback, useMemo, useRef, type RefObject } from 'react'

import { LemonDivider } from '@posthog/lemon-ui'

import { MarkdownEditorImageEmojiControls } from 'lib/components/MarkdownEditor/shared/MarkdownEditorImageEmojiControls'
import { RichMarkdownEditorFormatControls } from 'lib/components/MarkdownEditor/shared/RichMarkdownEditorFormatControls'

export type RichMarkdownEditorBubbleMenuProps = {
    editor: Editor | null
    linkUrl: string
    setLinkUrl: (url: string) => void
    showLinkPopover: boolean
    setShowLinkPopover: (visible: boolean) => void
    linkPopoverReferenceElement?: HTMLElement | null
    clearLinkPopoverReference?: () => void
    /** Editor shell (or content wrapper) used as drag-and-drop target for images */
    alternativeDropTargetRef: RefObject<HTMLElement | null>
    showImageUpload?: boolean
    showEmoji?: boolean
    emojiPopoverDataAttr?: string
}

export function RichMarkdownEditorBubbleMenu({
    editor,
    linkUrl,
    setLinkUrl,
    showLinkPopover,
    setShowLinkPopover,
    linkPopoverReferenceElement = null,
    clearLinkPopoverReference,
    alternativeDropTargetRef,
    showImageUpload = true,
    showEmoji = true,
    emojiPopoverDataAttr = 'inline-rich-markdown-bubble-emoji-popover',
}: RichMarkdownEditorBubbleMenuProps): JSX.Element | null {
    const menuRef = useRef<HTMLDivElement>(null)

    // Stable references: BubbleMenu re-runs plugin registration when these identities change.
    const shouldShow = useCallback(
        ({
            editor: { isEditable },
            view,
            state,
            from,
            to,
        }: {
            editor: Editor
            view: Editor['view']
            state: EditorState
            from: number
            to: number
        }) => {
            if (!isEditable) {
                return false
            }

            const isChildOfMenu = menuRef.current?.contains(document.activeElement)
            if (isChildOfMenu) {
                return true
            }

            const focused = view.hasFocus()
            const isTextBlock = isTextSelection(state.selection)

            if (!focused || !isTextBlock) {
                return false
            }

            return state.doc.textBetween(from, to).length > 0
        },
        []
    )

    const bubbleOptions = useMemo(() => ({ placement: 'top-start' as const }), [])

    if (!editor) {
        return null
    }

    const showMedia = showImageUpload || showEmoji

    return (
        <BubbleMenu editor={editor} shouldShow={shouldShow} options={bubbleOptions}>
            <div
                ref={menuRef}
                className="RichMarkdownEditor__bubble flex max-w-[min(100vw-2rem,56rem)] flex-nowrap items-center gap-x-0.5 overflow-x-auto overscroll-x-contain rounded border border-primary bg-surface-primary p-1 text-secondary shadow-md [scrollbar-width:thin]"
            >
                <div className="flex shrink-0 items-center gap-0.5">
                    <RichMarkdownEditorFormatControls
                        editor={editor}
                        linkUrl={linkUrl}
                        setLinkUrl={setLinkUrl}
                        showLinkPopover={showLinkPopover}
                        setShowLinkPopover={setShowLinkPopover}
                        linkPopoverReferenceElement={linkPopoverReferenceElement}
                        clearLinkPopoverReference={clearLinkPopoverReference}
                    />
                </div>
                {showMedia ? (
                    <div className="flex shrink-0 items-center gap-0.5">
                        <LemonDivider vertical className="mx-1 self-stretch" />
                        <MarkdownEditorImageEmojiControls
                            editor={editor}
                            alternativeDropTargetRef={alternativeDropTargetRef}
                            emojiPopoverDataAttr={emojiPopoverDataAttr}
                            showImageUpload={showImageUpload}
                            showEmoji={showEmoji}
                        />
                    </div>
                ) : null}
            </div>
        </BubbleMenu>
    )
}
