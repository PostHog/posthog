import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { Editor, isTextSelection } from '@tiptap/core'
import { BubbleMenu } from '@tiptap/react'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { IconBold, IconDelete, IconItalic, IconLink, IconOpenInNew } from 'lib/lemon-ui/icons'
import { isURL } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'

export const InlineMenu = ({ editor }: { editor: Editor }): JSX.Element => {
    const { href, target } = editor.getAttributes('link')
    const menuRef = useRef<HTMLDivElement>(null)
    const { ref: setRef, height } = useResizeObserver()

    const [position, setPosition] = useState<{ top: number }>({ top: 0 })

    const setLink = (href: string): void => {
        editor.commands.setMark('link', { href: href })
    }

    const openLink = (): void => {
        window.open(href, target)
    }

    const handleUpdate = (): void => {
        const selection = window.getSelection()

        if (selection && selection.anchorNode && selection.anchorNode.parentElement) {
            if (selection.anchorNode.nodeType === Node.ELEMENT_NODE) {
                // const position = (selection.anchorNode as HTMLElement).getBoundingClientRect()
                // console.log(position)

                const editorPos = editor.view.dom.getBoundingClientRect()
                const selectionPos = (selection.anchorNode as HTMLElement).getBoundingClientRect()

                setPosition({ top: selectionPos.top - editorPos.top })
            }
        }
    }

    useEffect(() => {
        editor.on('update', handleUpdate)
        editor.on('selectionUpdate', handleUpdate)
        setRef(editor.view.dom)
        return () => {
            editor.off('update', handleUpdate)
            editor.off('selectionUpdate', handleUpdate)
        }
    }, [])

    useEffect(() => {
        handleUpdate()
    }, [height])

    return (
        <>
            <div style={{ position: 'absolute', top: position.top, left: 0 }}>David</div>
            <BubbleMenu
                editor={editor}
                shouldShow={({ editor: { isEditable }, view, state, from, to }) => {
                    const isChildOfMenu = menuRef.current?.contains(document.activeElement)
                    const focused = view.hasFocus() || isChildOfMenu
                    const isTextBlock = isTextSelection(state.selection)

                    editor.view.nodeDOM(state.selection.$anchor.pos)

                    if (!focused || !isEditable || !isTextBlock) {
                        return false
                    }

                    return state.doc.textBetween(from, to).length > 0
                }}
            >
                <div
                    ref={menuRef}
                    className="NotebookInlineMenu flex bg-white rounded border items-center text-muted-alt p-1 space-x-0.5"
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
                                status="primary"
                                size="small"
                                disabledReason={!isURL(href) && 'Enter a URL.'}
                            />
                            <LemonButton
                                onClick={() => editor.chain().focus().unsetMark('link').run()}
                                icon={<IconDelete />}
                                status="danger"
                                size="small"
                            />
                        </>
                    ) : (
                        <>
                            <LemonButton
                                onClick={() => editor.chain().focus().toggleMark('bold').run()}
                                active={editor.isActive('bold')}
                                icon={<IconBold />}
                                size="small"
                                status={editor.isActive('bold') ? 'primary' : 'stealth'}
                            />
                            <LemonButton
                                onClick={() => editor.chain().focus().toggleMark('italic').run()}
                                active={editor.isActive('italic')}
                                icon={<IconItalic />}
                                status={editor.isActive('italic') ? 'primary' : 'stealth'}
                                size="small"
                            />
                            <LemonButton
                                onClick={() => editor.chain().focus().setMark('link').run()}
                                icon={<IconLink />}
                                status="stealth"
                                size="small"
                            />
                        </>
                    )}
                </div>
            </BubbleMenu>
        </>
    )
}

function getCaretCoordinates() {
    let x = 0,
        y = 0
    const isSupported = typeof window.getSelection !== 'undefined'
    if (isSupported) {
        const selection = window.getSelection()
        debugger
        if (selection && selection.rangeCount !== 0) {
            const range = selection.getRangeAt(0).cloneRange()
            range.collapse(true)
            const rect = range.getClientRects()[0]
            if (rect) {
                x = rect.left
                y = rect.top
            }
        }
    }
    return { x, y }
}
