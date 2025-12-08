import { JSONContent } from '@tiptap/core'
import { useActions, useValues } from 'kea'
import { useLayoutEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
import { LemonRichContentEditor } from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'

import { ElementRect } from '~/toolbar/types'

import { productToursLogic } from './productToursLogic'

const DEFAULT_STEP_CONTENT: JSONContent = {
    type: 'doc',
    content: [
        {
            type: 'heading',
            attrs: { level: 1 },
            content: [{ type: 'text', text: 'Step title' }],
        },
        {
            type: 'paragraph',
            content: [{ type: 'text', text: 'Describe what this element does...' }],
        },
    ],
}

type Position = 'right' | 'left' | 'top' | 'bottom'

function calculatePosition(
    targetRect: ElementRect,
    editorWidth: number,
    editorHeight: number,
    padding: number,
    preference: Position = 'right'
): { left: number; top: number } {
    const viewport = {
        width: window.innerWidth,
        height: window.innerHeight,
    }

    const spaceRight = viewport.width - (targetRect.left + targetRect.width)
    const spaceLeft = targetRect.left
    const spaceBottom = viewport.height - (targetRect.top + targetRect.height)
    const spaceTop = targetRect.top

    const fitsRight = spaceRight >= editorWidth + padding * 2
    const fitsLeft = spaceLeft >= editorWidth + padding * 2
    const fitsBottom = spaceBottom >= editorHeight + padding * 2
    const fitsTop = spaceTop >= editorHeight + padding * 2

    let position: Position = preference
    if (preference === 'right' && !fitsRight) {
        position = fitsLeft ? 'left' : fitsBottom ? 'bottom' : fitsTop ? 'top' : 'right'
    } else if (preference === 'left' && !fitsLeft) {
        position = fitsRight ? 'right' : fitsBottom ? 'bottom' : fitsTop ? 'top' : 'left'
    }

    let left: number
    let top: number

    if (position === 'right' || position === 'left') {
        left =
            position === 'right'
                ? targetRect.left + targetRect.width + padding
                : targetRect.left - editorWidth - padding

        // Try aligning top edges first
        top = targetRect.top

        // If that puts popup off screen at bottom, align bottom edges instead
        if (top + editorHeight > viewport.height - padding) {
            top = targetRect.top + targetRect.height - editorHeight
        }

        // Clamp to min padding if still off screen at top
        top = Math.max(padding, top)
    } else if (position === 'bottom') {
        left = targetRect.left
        top = targetRect.top + targetRect.height + padding
    } else {
        // top
        left = targetRect.left
        top = targetRect.top - editorHeight - padding
    }

    // Clamp horizontal to viewport edges
    const maxLeft = viewport.width - editorWidth - padding
    left = Math.max(padding, Math.min(left, maxLeft))

    return { left, top }
}

export function StepEditor({ rect }: { rect: ElementRect }): JSX.Element {
    const { editingStep } = useValues(productToursLogic)
    const { confirmStep, cancelStep } = useActions(productToursLogic)
    const [richEditor, setRichEditor] = useState<RichContentEditorType | null>(null)
    const editorRef = useRef<HTMLDivElement>(null)
    const [position, setPosition] = useState<{ left: number; top: number } | null>(null)

    const editorWidth = 320
    const padding = 16

    useLayoutEffect(() => {
        if (editorRef.current) {
            const editorHeight = editorRef.current.offsetHeight
            setPosition(calculatePosition(rect, editorWidth, editorHeight, padding, 'right'))
        }
    }, [rect])

    useLayoutEffect(() => {
        if (richEditor && editingStep?.content) {
            richEditor.setContent(editingStep.content)
        }
    }, [editingStep, richEditor])

    const getContent = (): JSONContent | null => {
        if (!richEditor) {
            return null
        }
        return richEditor.isEmpty() ? null : richEditor.getJSON()
    }

    const style: React.CSSProperties = {
        position: 'fixed',
        width: editorWidth,
        visibility: position ? 'visible' : 'hidden',
        ...(position ?? { left: 0, top: 0 }),
    }

    return (
        <div
            ref={editorRef}
            className="bg-bg-light rounded-lg shadow-lg border p-4 space-y-3"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ ...style, zIndex: 2147483020, pointerEvents: 'auto' }}
        >
            {/* <div className="font-semibold text-sm">Tour step</div> */}

            <LemonRichContentEditor
                initialContent={editingStep?.content ?? DEFAULT_STEP_CONTENT}
                onCreate={setRichEditor}
                enableRichFormatting
                enableHeadings
                disableMentions
                minRows={3}
                classNames="mt-0"
            />

            <div className="flex gap-2 pt-1">
                <LemonButton type="secondary" size="small" onClick={() => cancelStep()}>
                    Cancel
                </LemonButton>
                <LemonButton type="primary" size="small" onClick={() => confirmStep(getContent())}>
                    Save step
                </LemonButton>
            </div>
        </div>
    )
}
