/**
 * Raw stack frame in the shape error tracking ingests: `$exception_list[].stacktrace.frames`.
 * The frames stay minified here. The server symbolicates them from the uploaded sourcemaps.
 */
export interface RawStackFrame {
    platform: 'web:javascript'
    filename: string
    function: string
    lineno: number
    colno: number
    in_app: boolean
}

const MAX_FRAMES = 50

// V8/Chromium: "    at fn (https://host/app.js:1:2)" or "    at https://host/app.js:1:2"
const V8_LINE = /^\s*at (?:async )?(?:(.+?) \()?(.+?):(\d+):(\d+)\)?\s*$/
// SpiderMonkey and JavaScriptCore: "fn@https://host/app.js:1:2" or "@https://host/app.js:1:2"
const GECKO_LINE = /^\s*(.*?)@(.+?):(\d+):(\d+)\s*$/

/**
 * Browsers report injected code with two filenames: an `eval` frame as `<anonymous>`, and a Safari
 * extension frame as `webkit-masked-url://`. posthog-js keeps both out of `in_app`, and the server
 * copies the flag through for any frame that carries a line and a column. A frame marked as
 * application code here feeds the issue fingerprint and fills the default app-frame view.
 */
function isApplicationFrame(filename: string): boolean {
    return filename !== '<anonymous>' && !filename.startsWith('webkit-masked-url://')
}

/**
 * Minimal, dependency-free stack parser for the boot beacon. posthog-js has a full parser, but it
 * lives in the App chunk, which is the chunk a boot failure means we do not have.
 *
 * The returned order is bottom-up (entry point first, crash site last), which is the wire order
 * error tracking expects. Browsers print the opposite order.
 */
export function parseStackFrames(stack: string | undefined): RawStackFrame[] {
    if (!stack) {
        return []
    }
    const frames: RawStackFrame[] = []
    for (const line of stack.split('\n')) {
        const match = V8_LINE.exec(line) || GECKO_LINE.exec(line)
        if (!match) {
            continue
        }
        const filename = match[2]
        frames.push({
            platform: 'web:javascript',
            filename,
            function: match[1] || '?',
            lineno: Number(match[3]),
            colno: Number(match[4]),
            in_app: isApplicationFrame(filename),
        })
        if (frames.length === MAX_FRAMES) {
            break
        }
    }
    return frames.reverse()
}
