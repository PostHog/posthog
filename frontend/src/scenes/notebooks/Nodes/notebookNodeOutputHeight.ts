// Height for a SQL/Python V2 cell once its output lands. The default node height only fits a
// couple of table rows, but a scalar result doesn't need a tall cell either — so size to what
// actually came back and cap it, instead of snapping every result to one large default.

/** Tab bar, dataframe-name footer, and the padding around the output area. */
const NODE_CHROME_HEIGHT = 80
/** Table header plus the pagination bar under it. */
const TABLE_CHROME_HEIGHT = 68
const ROW_HEIGHT = 28
const TEXT_LINE_HEIGHT = 18
/** Beyond this the text scrolls — a long traceback shouldn't swallow the notebook. */
const MAX_TEXT_LINES = 12
/** Enough for a default-size matplotlib figure. */
const MEDIA_HEIGHT = 300
const MIN_OUTPUT_HEIGHT = 160
const MAX_OUTPUT_HEIGHT = 460

export type NotebookNodeOutputShape = {
    /** Rows in the returned page, not the total row count — only the page is rendered. */
    rowCount?: number
    textLines?: number
    hasMedia?: boolean
}

export const countTextLines = (...texts: (string | null | undefined)[]): number =>
    texts.reduce((lines: number, text) => lines + (text ? text.replace(/\n$/, '').split('\n').length : 0), 0)

/**
 * Height that fits the given output, clamped so a single value stays compact and a large
 * result grows to a readable — but still bounded — size. Returns null when there's nothing
 * to show, so callers leave the node's height alone.
 */
export const outputHeightForShape = ({
    rowCount = 0,
    textLines = 0,
    hasMedia = false,
}: NotebookNodeOutputShape): number | null => {
    let content = 0
    if (rowCount > 0) {
        content += TABLE_CHROME_HEIGHT + rowCount * ROW_HEIGHT
    }
    if (textLines > 0) {
        content += Math.min(textLines, MAX_TEXT_LINES) * TEXT_LINE_HEIGHT
    }
    if (hasMedia) {
        content += MEDIA_HEIGHT
    }
    if (content === 0) {
        return null
    }
    return Math.min(MAX_OUTPUT_HEIGHT, Math.max(MIN_OUTPUT_HEIGHT, NODE_CHROME_HEIGHT + content))
}
