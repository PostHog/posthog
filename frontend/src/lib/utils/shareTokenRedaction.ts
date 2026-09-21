import { BeforeSendFn, CapturedNetworkRequest } from 'posthog-js'

// Several pages carry a SharingConfiguration access token in their own URL, and anyone who holds a
// token can open what it shares. The hooks below strip every token shape the main app can see before
// an event or a recorded network request leaves the browser. Without them a token lands in
// $current_url, in the $referrer of the page navigated to next, and in the recorded request body,
// where every viewer of our own analytics and replay data could read and reuse it. The interview
// share page redacts its own token the same way, see frontend/src/exporter/index.tsx.
//
// The fork landing page holds the token in its path (/desktop/canvas-fork/<token>) and repeats it in
// the fork request body. The legacy /code/canvas-fork/<token> prefix is matched too: links shared
// before the move still land on it, and its pageview is captured before the redirect.
const CANVAS_FORK_PATH_RE = /(\/(?:desktop|code)\/canvas-fork\/)[^/?#]+/g
const SHARE_TOKEN_FIELD_RE = /("share_token"\s*:\s*")[^"]*"/g
// A shared page (/shared/<token>) sends the viewer to /login?next=/shared/<token> to sign in, so the
// token reaches the main app both percent-encoded in that query parameter and raw in the referrer.
const SHARED_PAGE_PATH_RE = /(\/shared\/)[^/?#&]+/g
const SHARED_PAGE_ENCODED_PATH_RE = /(%2Fshared%2F)[^&#%]+/gi
const REDACTED = '<redacted>'

export function redactShareTokens(value: string): string {
    return value
        .replace(CANVAS_FORK_PATH_RE, `$1${REDACTED}`)
        .replace(SHARE_TOKEN_FIELD_RE, `$1${REDACTED}"`)
        .replace(SHARED_PAGE_PATH_RE, `$1${REDACTED}`)
        .replace(SHARED_PAGE_ENCODED_PATH_RE, `$1${REDACTED}`)
}

// Every string property is redacted instead of a fixed list of URL properties, because the token
// rides on more than one: $current_url and $pathname on the landing page itself, $referrer once the
// page forwards on, and $prev_pageview_pathname on the pageleave in between.
export const shareTokenBeforeSend: BeforeSendFn = (event) => {
    if (event?.properties) {
        for (const [key, value] of Object.entries(event.properties)) {
            if (typeof value === 'string') {
                event.properties[key] = redactShareTokens(value)
            }
        }
    }
    return event
}

export function shareTokenMaskNetworkRequest(request: CapturedNetworkRequest): CapturedNetworkRequest {
    if (request.name) {
        request.name = redactShareTokens(request.name)
    }
    if (request.requestBody) {
        request.requestBody = redactShareTokens(request.requestBody)
    }
    return request
}
