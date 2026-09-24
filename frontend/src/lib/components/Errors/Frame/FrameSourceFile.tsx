import { useActions, useValues } from 'kea'
import { useLayoutEffect, useRef } from 'react'

import { Language } from 'lib/components/CodeSnippet'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { ErrorTrackingStackFrameContext } from '../types'
import { FrameContext } from './FrameContext'
import { FrameSourceFileTarget, frameSourceFileLogic } from './frameSourceFileLogic'

// How close to an edge of the box, in pixels, a scroll shows more lines.
const EDGE_PX = 48

export function FrameSourceFile({
    target,
    context,
    language,
}: {
    target: FrameSourceFileTarget
    context: ErrorTrackingStackFrameContext | null
    language: Language
}): JSX.Element {
    const logic = frameSourceFileLogic({ ...target, capturedLine: context?.line.line ?? null })
    const { sourceFile, sourceFileLoading, fileWindow, capturedCodeCheck } = useValues(logic)
    const { showMoreAbove, showMoreBelow } = useActions(logic)
    const boxRef = useRef<HTMLDivElement>(null)
    const heightBeforeLinesAbove = useRef<number | null>(null)
    const centered = useRef(false)

    useLayoutEffect(() => {
        const box = boxRef.current
        if (!box || !fileWindow || centered.current) {
            return
        }
        const { before, after } = fileWindow.context
        const rowHeight = box.scrollHeight / (before.length + 1 + after.length)
        box.scrollTop = rowHeight * before.length - (box.clientHeight - rowHeight) / 2
        centered.current = true
    }, [fileWindow])

    // Lines added above would push the visible lines down, so the scroll moves by the same height.
    const linesBefore = fileWindow?.context.before.length
    useLayoutEffect(() => {
        const box = boxRef.current
        if (box && heightBeforeLinesAbove.current !== null) {
            box.scrollTop += box.scrollHeight - heightBeforeLinesAbove.current
            heightBeforeLinesAbove.current = null
        }
    }, [linesBefore])

    const onScroll = (): void => {
        const box = boxRef.current
        if (!box || !fileWindow) {
            return
        }
        if (box.scrollTop < EDGE_PX && fileWindow.hasMoreAbove && heightBeforeLinesAbove.current === null) {
            heightBeforeLinesAbove.current = box.scrollHeight
            showMoreAbove()
        } else if (box.scrollHeight - box.scrollTop - box.clientHeight < EDGE_PX && fileWindow.hasMoreBelow) {
            showMoreBelow()
        }
    }

    if (!sourceFile || !fileWindow || capturedCodeCheck === 'differs') {
        return (
            <>
                {context ? (
                    <FrameContext context={context} language={language} />
                ) : sourceFileLoading ? (
                    <div className="p-2">
                        <Spinner />
                    </div>
                ) : (
                    <p className="m-0 p-2 text-xs text-muted">The source of this frame isn't available.</p>
                )}
                {capturedCodeCheck === 'differs' && (
                    <p className="m-0 border-t px-2 py-1 text-xs text-muted">
                        The file at the release commit doesn't match the captured code, so only the captured lines are
                        shown.
                    </p>
                )}
            </>
        )
    }

    return (
        <div>
            <div className="flex items-center justify-between gap-2 border-b px-2 py-1 text-xs text-muted">
                <span className="truncate font-mono" title={sourceFile.repo_path}>
                    {sourceFile.repo_path} at {sourceFile.commit.slice(0, 7)}
                </span>
                {capturedCodeCheck === 'unchecked' && (
                    <span className="shrink-0">Not compared with the captured code</span>
                )}
            </div>
            <div
                ref={boxRef}
                onScroll={onScroll}
                className="max-h-96 overflow-y-auto"
                data-attr="error-tracking-frame-source-file"
            >
                <FrameContext context={fileWindow.context} language={language} />
            </div>
        </div>
    )
}
