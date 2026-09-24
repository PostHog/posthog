import { ErrorTrackingStackFrameContext, ErrorTrackingStackFrameContextLine } from '../types'

export interface SourceFileWindow {
    context: ErrorTrackingStackFrameContext
    hasMoreAbove: boolean
    hasMoreBelow: boolean
}

export type CapturedCodeCheck = 'matches' | 'differs' | 'unchecked'

// Cymbal marks a captured line it cut at 300 characters with this suffix.
const TRUNCATION_SUFFIX = '...✂️'

/** The lines of a file around the frame line, as a frame context. */
export function sourceFileWindow(
    lines: string[],
    line: number | null,
    linesAbove: number,
    linesBelow: number
): SourceFileWindow | null {
    if (!line || line < 1 || line > lines.length) {
        return null
    }
    const anchor = line - 1
    const start = Math.max(0, anchor - linesAbove)
    const end = Math.min(lines.length, anchor + 1 + linesBelow)
    const contextLine = (index: number): ErrorTrackingStackFrameContextLine => ({
        number: index + 1,
        line: lines[index],
    })
    const indexes = (from: number, to: number): number[] => Array.from({ length: to - from }, (_, i) => from + i)
    return {
        context: {
            before: indexes(start, anchor).map(contextLine),
            line: contextLine(anchor),
            after: indexes(anchor + 1, end).map(contextLine),
        },
        hasMoreAbove: start > 0,
        hasMoreBelow: end < lines.length,
    }
}

/**
 * Whether the file at the release commit has, at the frame line, the code the SDK or symbol set
 * captured. A difference means the release commit is not the code that ran.
 */
export function checkCapturedCode(
    lines: string[],
    line: number | null,
    capturedLine: string | null
): CapturedCodeCheck {
    if (capturedLine === null) {
        return 'unchecked'
    }
    const fileLine = line ? lines[line - 1] : undefined
    if (fileLine === undefined) {
        return 'differs'
    }
    const captured = capturedLine.trim()
    if (captured.endsWith(TRUNCATION_SUFFIX)) {
        return fileLine.trim().startsWith(captured.slice(0, -TRUNCATION_SUFFIX.length)) ? 'matches' : 'differs'
    }
    return fileLine.trim() === captured ? 'matches' : 'differs'
}
