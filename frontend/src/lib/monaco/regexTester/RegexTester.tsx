import './RegexTester.scss'

import { useActions, useValues } from 'kea'
import { IDisposable, KeyCode, editor as importedEditor } from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'

import { Popover } from 'lib/lemon-ui/Popover'

import { RegexLiteral, findRegexLiterals } from './findRegexLiterals'
import { regexTesterLogic } from './regexTesterLogic'
import { RegexTesterOverlay } from './RegexTesterOverlay'

const OPEN_DELAY_MS = 300
/** Long enough to cross the gap between the underlined text and the popover. */
const CLOSE_DELAY_MS = 250
const RESCAN_DEBOUNCE_MS = 200

export interface RegexTesterProps {
    editor: importedEditor.IStandaloneCodeEditor
    logicKey: string
}

interface Anchor {
    top: number
    left: number
    width: number
    height: number
}

/**
 * Underlines the regex patterns in a query and offers a popover to try them against a sample
 * value, so a pattern can be checked without running the query.
 */
export function RegexTester({ editor, logicKey }: RegexTesterProps): JSX.Element {
    const { pattern } = useValues(regexTesterLogic({ logicKey }))
    const { openTester, closeTester } = useActions(regexTesterLogic({ logicKey }))

    const [anchor, setAnchor] = useState<Anchor | null>(null)
    const [anchorElement, setAnchorElement] = useState<HTMLDivElement | null>(null)

    const literalsRef = useRef<RegexLiteral[]>([])
    const hoveredRef = useRef<RegexLiteral | null>(null)
    const openTimeoutRef = useRef<number | null>(null)
    const closeTimeoutRef = useRef<number | null>(null)
    // The popover's mouseenter arrives before the editor's mouseleave, so cancelling the close on
    // enter alone gets undone a moment later. This flag makes where the pointer is the authority,
    // rather than the order the two events happen to arrive in.
    const pointerInsidePopoverRef = useRef(false)
    // Let the popover's own handlers drive the same close paths the effect sets up.
    const closeRef = useRef<() => void>(() => {})
    const scheduleCloseRef = useRef<() => void>(() => {})

    useEffect(() => {
        const decorations = editor.createDecorationsCollection([])
        const disposables: IDisposable[] = []
        let rescanTimeout: number | null = null

        const cancel = (ref: React.MutableRefObject<number | null>): void => {
            if (ref.current !== null) {
                window.clearTimeout(ref.current)
                ref.current = null
            }
        }

        const close = (): void => {
            cancel(openTimeoutRef)
            cancel(closeTimeoutRef)
            hoveredRef.current = null
            pointerInsidePopoverRef.current = false
            setAnchor(null)
            closeTester()
        }
        closeRef.current = close

        const anchorFor = (literal: RegexLiteral): Anchor | null => {
            const model = editor.getModel()
            if (!model) {
                return null
            }
            const startPosition = model.getPositionAt(literal.start)
            const endPosition = model.getPositionAt(literal.end)
            const start = editor.getScrolledVisiblePosition(startPosition)
            if (!start) {
                return null
            }
            const end = editor.getScrolledVisiblePosition(endPosition)
            const sameLine = end && endPosition.lineNumber === startPosition.lineNumber
            return {
                top: start.top,
                left: start.left,
                width: sameLine ? Math.max(end.left - start.left, 0) : 0,
                height: start.height,
            }
        }

        const scheduleOpen = (literal: RegexLiteral): void => {
            cancel(closeTimeoutRef)
            const hovered = hoveredRef.current
            if (hovered?.start === literal.start && hovered?.end === literal.end) {
                return
            }
            cancel(openTimeoutRef)
            openTimeoutRef.current = window.setTimeout(() => {
                openTimeoutRef.current = null
                const next = anchorFor(literal)
                if (!next) {
                    return
                }
                hoveredRef.current = literal
                setAnchor(next)
                openTester(literal.pattern)
            }, OPEN_DELAY_MS)
        }

        const scheduleClose = (): void => {
            cancel(openTimeoutRef)
            if (!hoveredRef.current || pointerInsidePopoverRef.current || closeTimeoutRef.current !== null) {
                return
            }
            closeTimeoutRef.current = window.setTimeout(close, CLOSE_DELAY_MS)
        }
        scheduleCloseRef.current = scheduleClose

        const rescan = (): void => {
            const model = editor.getModel()
            if (!model) {
                return
            }
            const literals = findRegexLiterals(model.getValue())
            literalsRef.current = literals
            decorations.set(
                literals.map((literal) => {
                    const start = model.getPositionAt(literal.start)
                    const end = model.getPositionAt(literal.end)
                    return {
                        range: {
                            startLineNumber: start.lineNumber,
                            startColumn: start.column,
                            endLineNumber: end.lineNumber,
                            endColumn: end.column,
                        },
                        options: { inlineClassName: 'RegexTester__literal' },
                    }
                })
            )
            const hovered = hoveredRef.current
            // The pattern the popover is testing may have just been edited out from under it.
            if (hovered && !literals.some((literal) => literal.start === hovered.start)) {
                close()
            }
        }

        rescan()

        disposables.push(
            editor.onDidChangeModelContent(() => {
                if (rescanTimeout !== null) {
                    window.clearTimeout(rescanTimeout)
                }
                rescanTimeout = window.setTimeout(rescan, RESCAN_DEBOUNCE_MS)
            }),
            editor.onDidChangeModel(() => rescan()),
            editor.onMouseMove((event) => {
                const model = editor.getModel()
                const position = event.target.position
                if (!model || !position) {
                    scheduleClose()
                    return
                }
                const offset = model.getOffsetAt(position)
                const literal = literalsRef.current.find(
                    (candidate) => offset >= candidate.start && offset <= candidate.end
                )
                if (literal) {
                    scheduleOpen(literal)
                } else {
                    scheduleClose()
                }
            }),
            editor.onMouseLeave(() => scheduleClose()),
            // Keeping the popover glued to the text through a scroll fights Monaco's own scroll
            // handling, so it steps out of the way instead.
            editor.onDidScrollChange(() => {
                if (hoveredRef.current) {
                    close()
                }
            }),
            editor.onKeyDown((event) => {
                if (event.keyCode === KeyCode.Escape && hoveredRef.current) {
                    close()
                }
            })
        )

        return () => {
            cancel(openTimeoutRef)
            cancel(closeTimeoutRef)
            if (rescanTimeout !== null) {
                window.clearTimeout(rescanTimeout)
            }
            disposables.forEach((disposable) => disposable.dispose())
            try {
                decorations.clear()
            } catch {
                // editor already disposed
            }
        }
    }, [editor, openTester, closeTester])

    return (
        <>
            {anchor && (
                <div
                    ref={setAnchorElement}
                    className="absolute pointer-events-none"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ top: anchor.top, left: anchor.left, width: anchor.width, height: anchor.height }}
                />
            )}
            <Popover
                visible={!!pattern && !!anchorElement}
                referenceElement={anchorElement}
                placement="bottom-start"
                onClickOutside={() => closeRef.current()}
                onMouseEnterInside={() => {
                    pointerInsidePopoverRef.current = true
                    if (closeTimeoutRef.current !== null) {
                        window.clearTimeout(closeTimeoutRef.current)
                        closeTimeoutRef.current = null
                    }
                }}
                onMouseLeaveInside={() => {
                    pointerInsidePopoverRef.current = false
                    scheduleCloseRef.current()
                }}
                overlay={<RegexTesterOverlay logicKey={logicKey} onClose={() => closeRef.current()} />}
            />
        </>
    )
}
