import { redactReplayRequests } from './replayRequestRedaction'

const REDACTED_BODY = '[SessionRecording] body redacted as it holds the values of a push send'
const PUSH_SEND_PATH = /\/messaging\/send\/push(_batch)?\/?(\?|#|$)/
// A workflow or broadcast test send, which carries the typed push content and the test person's properties.
const HOG_FLOW_TEST_SEND_PATH = /\/hog_flows\/[^/?#]+\/invocations\/?(\?|#|$)/

function redactPushSend(request: unknown): unknown {
    if (!request || typeof request !== 'object') {
        return request
    }
    const { name, requestBody } = request as Record<string, unknown>
    if (
        typeof name !== 'string' ||
        !(PUSH_SEND_PATH.test(name) || HOG_FLOW_TEST_SEND_PATH.test(name)) ||
        requestBody === undefined ||
        requestBody === null
    ) {
        return request
    }
    return { ...request, requestBody: REDACTED_BODY }
}

// A test send holds whatever the person typed, such as a login code, under names the SDK's scrubbing doesn't know.
export const redactPushSendsInReplay = redactReplayRequests(redactPushSend)
