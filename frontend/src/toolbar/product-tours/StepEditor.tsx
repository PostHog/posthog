import { JSONContent } from '@tiptap/core'
import { useActions, useValues } from 'kea'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { IconChevronRight, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { ElementRect } from '~/toolbar/types'
import { elementToActionStep } from '~/toolbar/utils'

import { ToolbarEditor, ToolbarRichTextEditor } from './ToolbarRichTextEditor'
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
    const { editingStep, selectedElement, dataAttributes, inspectingElement } = useValues(productToursLogic)
    const { confirmStep, cancelStep, removeStep } = useActions(productToursLogic)
    const [richEditor, setRichEditor] = useState<ToolbarEditor | null>(null)
    const editorRef = useRef<HTMLDivElement>(null)
    const [position, setPosition] = useState<{ left: number; top: number } | null>(null)
    const [selector, setSelector] = useState('')
    const [showAdvanced, setShowAdvanced] = useState(false)

    const editorWidth = 320
    const padding = 16

    // Initialize selector from editingStep or derive from selectedElement
    useEffect(() => {
        if (editingStep?.selector) {
            setSelector(editingStep.selector)
        } else if (selectedElement) {
            const actionStep = elementToActionStep(selectedElement, dataAttributes)
            setSelector(actionStep.selector ?? '')
        }
    }, [editingStep, selectedElement, dataAttributes])

    useLayoutEffect(() => {
        if (editorRef.current) {
            const editorHeight = editorRef.current.offsetHeight
            setPosition(calculatePosition(rect, editorWidth, editorHeight, padding, 'right'))
        }
    }, [rect])

    // Update editor when editing a different step
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

    const actionLabel = editingStep ? `Editing Step ${inspectingElement! + 1}` : 'Adding new step'

    return (
        <div
            ref={editorRef}
            className="bg-white rounded-lg space-y-0 overflow-hidden toolbar-animate-slide-up"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                ...style,
                zIndex: 2147483020,
                pointerEvents: 'auto',
                border: '1px solid #e5e7eb',
                boxShadow: '0 4px 24px rgba(0, 0, 0, 0.15), 0 0 0 1px rgba(0, 0, 0, 0.05)',
            }}
        >
            {/* Header showing current action */}
            <div
                className="text-white text-xs font-medium px-3 py-1.5"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ backgroundColor: '#1d4aff' }}
            >
                {actionLabel}
            </div>

            <div className="p-4 space-y-3">
                <ToolbarRichTextEditor
                    initialContent={editingStep?.content ?? DEFAULT_STEP_CONTENT}
                    onCreate={setRichEditor}
                    minRows={3}
                />

                <div className="space-y-1">
                    <button
                        type="button"
                        onClick={() => setShowAdvanced(!showAdvanced)}
                        className="flex items-center gap-1 text-xs text-muted hover:text-default transition-colors"
                    >
                        <IconChevronRight
                            className={`w-3 h-3 transition-transform ${showAdvanced ? 'rotate-90' : ''}`}
                        />
                        Advanced
                        {!showAdvanced && selector && (
                            <span className="font-mono text-[10px] ml-1 truncate max-w-[150px]">({selector})</span>
                        )}
                    </button>
                    {showAdvanced && (
                        <LemonInput
                            value={selector}
                            onChange={setSelector}
                            placeholder="CSS selector (e.g., #my-button)"
                            size="small"
                            fullWidth
                            className="font-mono text-xs"
                        />
                    )}
                </div>

                <div className="flex items-center justify-between">
                    <div className="flex gap-2 pt-1">
                        <LemonButton type="secondary" size="small" onClick={() => cancelStep()}>
                            Cancel
                        </LemonButton>
                        <LemonButton type="primary" size="small" onClick={() => confirmStep(getContent(), selector)}>
                            Done
                        </LemonButton>
                    </div>
                    <LemonButton
                        icon={<IconTrash />}
                        type="secondary"
                        status="danger"
                        size="small"
                        onClick={() => {
                            if (inspectingElement !== null) {
                                removeStep(inspectingElement)
                                cancelStep()
                            }
                        }}
                        tooltip="Delete this step"
                    />
                </div>
            </div>
        </div>
    )
}
