import { FormEvent, KeyboardEvent, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { updateNotebookCodeBlockText } from './documentModel'
import { findTextPosition, getElementLineHeight, isSelectionAnchoredInsideElement } from './domSelection'
import { TextSelectionPointerStartEvent } from './editorTypes'
import { NotebookBlockNode, NotebookCodeBlockNode, NotebookCodeRefMark, NotebookMode } from './types'

function measureCharacterRect(element: HTMLElement, offset: number): DOMRect | null {
    const startPosition = findTextPosition(element, offset)
    const endPosition = findTextPosition(element, offset + 1)
    const range = element.ownerDocument.createRange()
    range.setStart(startPosition.node, startPosition.offset)
    range.setEnd(endPosition.node, endPosition.offset)
    // jsdom ranges have no getClientRects; callers fall back to the computed line-height there
    const rect = typeof range.getClientRects === 'function' ? range.getClientRects()[0] : undefined
    return rect && (rect.height > 0 || rect.top !== 0) ? rect : null
}

// Measures the rendered top of every logical code line so the line-number gutter stays aligned with
// lines that wrap onto multiple visual rows. Each line's top comes from the rect of its first
// character (or, for empty lines, the newline terminating them), so error never accumulates across
// lines. Falls back to stacking the computed line-height where rects are unavailable.
function measureCodeLineTops(element: HTMLElement, lines: string[]): number[] {
    const lineHeight = getElementLineHeight(element)
    const elementTop = typeof element.getBoundingClientRect === 'function' ? element.getBoundingClientRect().top : 0
    const textLength = (element.textContent ?? '').length
    const tops: number[] = []
    let offset = 0
    let fallbackTop = 0

    for (const line of lines) {
        let top = fallbackTop

        if (offset < textLength) {
            // The line's first character — or the "\n" terminating an empty line, which renders on
            // the empty line itself.
            const rect = measureCharacterRect(element, offset)
            if (rect) {
                // rect.top is the glyph-box top; recenter to the line-box top so the gutter number
                // (which renders its own glyph with the same half-leading) lines up exactly.
                top = rect.top - elementTop - Math.max(0, (lineHeight - rect.height) / 2)
            }
        } else if (offset > 0) {
            // Trailing empty line with no terminating character: one row below the previous "\n".
            const rect = measureCharacterRect(element, offset - 1)
            if (rect) {
                top = rect.top - elementTop - Math.max(0, (lineHeight - rect.height) / 2) + lineHeight
            }
        }

        tops.push(top)
        fallbackTop = top + lineHeight
        offset += line.length + 1
    }

    return tops
}

function areNumberArraysEqual(left: number[], right: number[]): boolean {
    return left.length === right.length && left.every((value, index) => value === right[index])
}

type CodeRefRect = {
    refId: string
    top: number
    left: number
    width: number
    height: number
}

// Code renders as plain text (input handling reads `textContent`), so comment highlights can't be
// inline spans — they're measured from each anchor's text range and painted as an absolutely
// positioned overlay behind the text, one box per rendered line fragment.
function measureCodeRefRects(
    frameElement: HTMLElement,
    codeElement: HTMLElement,
    refs: NotebookCodeRefMark[]
): CodeRefRect[] {
    if (typeof frameElement.getBoundingClientRect !== 'function') {
        return []
    }

    const frameRect = frameElement.getBoundingClientRect()
    const textLength = (codeElement.textContent ?? '').length
    const rects: CodeRefRect[] = []
    for (const ref of refs) {
        const start = Math.min(ref.start, textLength)
        const end = Math.min(ref.end, textLength)
        if (end <= start) {
            continue
        }

        const startPosition = findTextPosition(codeElement, start)
        const endPosition = findTextPosition(codeElement, end)
        const range = codeElement.ownerDocument.createRange()
        range.setStart(startPosition.node, startPosition.offset)
        range.setEnd(endPosition.node, endPosition.offset)
        // jsdom ranges have no getClientRects; the highlight is skipped there
        if (typeof range.getClientRects !== 'function') {
            continue
        }

        for (const rect of Array.from(range.getClientRects())) {
            if (!rect.width || !rect.height) {
                continue
            }
            rects.push({
                refId: ref.id,
                top: rect.top - frameRect.top,
                left: rect.left - frameRect.left,
                width: rect.width,
                height: rect.height,
            })
        }
    }

    return rects
}

function areCodeRefRectsEqual(left: CodeRefRect[], right: CodeRefRect[]): boolean {
    return (
        left.length === right.length &&
        left.every((rect, index) => {
            const other = right[index]
            return (
                rect.refId === other.refId &&
                rect.top === other.top &&
                rect.left === other.left &&
                rect.width === other.width &&
                rect.height === other.height
            )
        })
    )
}

// A trailing <br> makes the final empty line visible: browsers collapse a trailing "\n" in
// pre-wrap rendering, so without the sentinel trailing blank lines would not render or be
// reachable with the caret. <br> contributes nothing to textContent, so text offsets are stable.
function syncTrailingLineBreakSentinel(element: HTMLElement, text: string): void {
    const hasSentinel = element.lastChild instanceof HTMLBRElement
    if (text.endsWith('\n') && !hasSentinel) {
        element.appendChild(element.ownerDocument.createElement('br'))
    } else if (!text.endsWith('\n') && hasSentinel && element.lastChild) {
        element.removeChild(element.lastChild)
    }
}

export function EditableCodeBlock({
    node,
    mode,
    setBlockRef,
    updateNode,
    deleteSelectedNotebookBlocks,
    handleSelectionChange,
    startTextSelectionPointer,
}: {
    node: NotebookCodeBlockNode
    mode: NotebookMode
    setBlockRef: (element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    deleteSelectedNotebookBlocks: () => boolean
    handleSelectionChange: () => void
    startTextSelectionPointer: (event: TextSelectionPointerStartEvent) => void
}): JSX.Element {
    const elementRef = useRef<HTMLPreElement | null>(null)
    const frameRef = useRef<HTMLDivElement | null>(null)
    const skipDomSyncForTextRef = useRef<string | null>(null)
    const [lineTops, setLineTops] = useState<number[]>([])
    const [refRects, setRefRects] = useState<CodeRefRect[]>([])

    const lines = node.text.split('\n')
    const refs = node.refs

    const setElementRef = useCallback(
        (element: HTMLPreElement | null): void => {
            elementRef.current = element
            setBlockRef(element)
        },
        [setBlockRef]
    )

    useLayoutEffect(() => {
        const element = elementRef.current
        if (!element) {
            return
        }

        const selection = window.getSelection()
        const shouldSkipOwnInputSync =
            (document.activeElement === element || isSelectionAnchoredInsideElement(selection, element)) &&
            skipDomSyncForTextRef.current === node.text
        skipDomSyncForTextRef.current = null

        if (shouldSkipOwnInputSync) {
            return
        }

        if (element.textContent !== node.text) {
            element.textContent = node.text
        }
        syncTrailingLineBreakSentinel(element, node.text)
    }, [node.id, node.text])

    const measureLineTops = useCallback((): void => {
        const element = elementRef.current
        if (!element) {
            return
        }

        const nextTops = measureCodeLineTops(element, (element.textContent ?? '').split('\n'))
        setLineTops((currentTops) => (areNumberArraysEqual(currentTops, nextTops) ? currentTops : nextTops))
    }, [])

    const measureRefRects = useCallback((): void => {
        const element = elementRef.current
        const frameElement = frameRef.current
        if (!element || !frameElement) {
            return
        }

        const nextRects = refs?.length ? measureCodeRefRects(frameElement, element, refs) : []
        setRefRects((currentRects) => (areCodeRefRectsEqual(currentRects, nextRects) ? currentRects : nextRects))
    }, [refs])

    useLayoutEffect(() => {
        measureLineTops()
        measureRefRects()
    }, [measureLineTops, measureRefRects, node.text])

    useEffect(() => {
        const element = elementRef.current
        if (!element || typeof ResizeObserver === 'undefined') {
            return
        }

        const observer = new ResizeObserver(() => {
            measureLineTops()
            measureRefRects()
        })
        observer.observe(element)
        return () => observer.disconnect()
    }, [measureLineTops, measureRefRects])

    const updateText = (text: string): void => {
        skipDomSyncForTextRef.current = text
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'code') {
                return currentNode
            }

            return updateNotebookCodeBlockText(currentNode, text)
        })
    }

    const handleInput = (event: FormEvent<HTMLPreElement>): void => {
        updateText(event.currentTarget.textContent ?? '')
    }

    const handleKeyDown = (event: KeyboardEvent<HTMLPreElement>): void => {
        if ((event.key === 'Backspace' || event.key === 'Delete') && deleteSelectedNotebookBlocks()) {
            event.preventDefault()
            event.stopPropagation()
        }
    }

    return (
        <div className="MarkdownNotebook__code-block-frame" ref={frameRef}>
            {refRects.length ? (
                <div className="MarkdownNotebook__code-ref-overlay" contentEditable={false} aria-hidden="true">
                    {refRects.map((rect, rectIndex) => (
                        <div
                            key={`${rect.refId}-${rectIndex}`}
                            className="MarkdownNotebook__code-ref-highlight"
                            data-notebook-ref={rect.refId}
                            style={{
                                top: `${rect.top}px`,
                                left: `${rect.left}px`,
                                width: `${rect.width}px`,
                                height: `${rect.height}px`,
                            }}
                        />
                    ))}
                </div>
            ) : null}
            <div
                className="MarkdownNotebook__code-block-gutter"
                contentEditable={false}
                aria-hidden="true"
                style={{ width: `${Math.max(2, String(lines.length).length)}ch` }}
            >
                {lines.map((_, lineIndex) => (
                    <div
                        key={lineIndex}
                        className="MarkdownNotebook__code-block-line-number"
                        style={lineTops[lineIndex] !== undefined ? { top: `${lineTops[lineIndex]}px` } : undefined}
                    >
                        {lineIndex + 1}
                    </div>
                ))}
            </div>
            <pre
                className="MarkdownNotebook__code-block"
                ref={setElementRef}
                contentEditable={mode === 'edit'}
                data-markdown-notebook-node-id={node.id}
                data-placeholder="Code"
                onInput={handleInput}
                onKeyDown={handleKeyDown}
                onMouseDown={startTextSelectionPointer}
                onPointerDown={startTextSelectionPointer}
                onTouchStart={startTextSelectionPointer}
                onMouseUp={handleSelectionChange}
                onKeyUp={handleSelectionChange}
                spellCheck={false}
                suppressContentEditableWarning
            />
            <div className="MarkdownNotebook__code-block-actions" contentEditable={false}>
                <LemonButton
                    size="xsmall"
                    icon={<IconCopy />}
                    tooltip="Copy code"
                    aria-label="Copy code"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => void copyToClipboard(node.text, 'code')}
                />
            </div>
        </div>
    )
}
