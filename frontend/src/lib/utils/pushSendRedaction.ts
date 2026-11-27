import { redactReplayRequests } from './replayRequestRedaction'

const REDACTED_BODY = '[SessionRecording] body redacted as it holds the values of a push send'
const PUSH_SEND_PATH = /\/messaging\/send\/push(_batch)?\/?(\?|#|$)/
// A workflow, broadcast or destination test send, which carries the typed push content and the test person's properties.
const HOG_FLOW_TEST_SEND_PATH = /\/hog_(flows|functions)\/[^/?#]+\/invocations\/?(\?|#|$)/
// The push log lists each send's title and recipient.
const PUSH_LOG_PATH = /\/transactional_push_log\/?(\?|#|$)/
// The email log lists each send's recipient address. Its counts under stats/ hold no recipient.
const EMAIL_LOG_PATH = /\/transactional_email_log\/(?!stats)[^?#]*(\?|#|$)/

const isSet = (body: unknown): boolean => body !== undefined && body !== null

function redactPushSend(request: unknown): unknown {
    if (!request || typeof request !== 'object') {
        return request
    }
    const { name, requestBody, responseBody } = request as Record<string, unknown>
    if (
        typeof name !== 'string' ||
        ![PUSH_SEND_PATH, HOG_FLOW_TEST_SEND_PATH, PUSH_LOG_PATH, EMAIL_LOG_PATH].some((path) => path.test(name))
    ) {
        return request
    }
    // A log search is part of a recipient's distinct ID or email address.
    const scrubbedName =
        PUSH_LOG_PATH.test(name) || EMAIL_LOG_PATH.test(name)
            ? name.replace(/([?&]search=)[^&#]*/g, '$1[redacted]')
            : name
    if (!isSet(requestBody) && !isSet(responseBody) && scrubbedName === name) {
        return request
    }
    // A test send's response can echo the push it sent in its logs.
    return {
        ...request,
        name: scrubbedName,
        ...(isSet(requestBody) ? { requestBody: REDACTED_BODY } : {}),
        ...(isSet(responseBody) ? { responseBody: REDACTED_BODY } : {}),
    }
}

// A test send holds whatever the person typed, such as a login code, under names the SDK's scrubbing doesn't know.
export const redactPushSendsInReplay = redactReplayRequests(redactPushSend)
