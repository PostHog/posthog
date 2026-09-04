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
        frames.push({
            platform: 'web:javascript',
            filename: match[2],
            function: match[1] || '?',
            lineno: Number(match[3]),
            colno: Number(match[4]),
            in_app: true,
        })
        if (frames.length === MAX_FRAMES) {
            break
        }
    }
    return frames.reverse()
}
