import { BeforeSendFn, CapturedNetworkRequest } from 'posthog-js'

// The fork landing page carries a SharingConfiguration access token in its own URL
// (/desktop/canvas-fork/<token>), and the fork request repeats that token in its body. Anyone who
// holds the token can copy the canvas, so both hooks below strip it before an event or a recorded
// network request leaves the browser. Without them the token lands in $current_url, in the
// $referrer of the page the scene forwards to, and in the recorded request body, where every
// viewer of our own analytics and replay data could read and reuse it. The interview share page
// redacts its token the same way, see frontend/src/exporter/index.tsx.
const FORK_PATH_TOKEN_RE = /(\/desktop\/canvas-fork\/)[^/?#]+/g
const SHARE_TOKEN_FIELD_RE = /("share_token"\s*:\s*")[^"]*"/g
const REDACTED = '<redacted>'

export function redactCanvasForkToken(value: string): string {
    return value.replace(FORK_PATH_TOKEN_RE, `$1${REDACTED}`).replace(SHARE_TOKEN_FIELD_RE, `$1${REDACTED}"`)
}

// Every string property is redacted instead of a fixed list of URL properties, because the token
// rides on more than one: $current_url and $pathname on the landing page itself, $referrer once the
// scene forwards to the copy, and $prev_pageview_pathname on the pageleave in between.
export const canvasForkBeforeSend: BeforeSendFn = (event) => {
    if (event?.properties) {
        for (const [key, value] of Object.entries(event.properties)) {
            if (typeof value === 'string') {
                event.properties[key] = redactCanvasForkToken(value)
            }
        }
    }
    return event
}

export function canvasForkMaskNetworkRequest(request: CapturedNetworkRequest): CapturedNetworkRequest {
    if (request.name) {
        request.name = redactCanvasForkToken(request.name)
    }
    if (request.requestBody) {
        request.requestBody = redactCanvasForkToken(request.requestBody)
    }
    return request
}
