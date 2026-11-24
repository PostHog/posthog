import { redactReplayRequests } from './replayRequestRedaction'

const REDACTED_BODY = '[SessionRecording] body redacted as it holds the values of a push send'
const PUSH_SEND_PATH = /\/messaging\/send\/push(_batch)?\/?(\?|#|$)/

function redactPushSend(request: unknown): unknown {
    if (!request || typeof request !== 'object') {
        return request
    }
    const { name, requestBody } = request as Record<string, unknown>
    if (typeof name !== 'string' || !PUSH_SEND_PATH.test(name) || requestBody === undefined || requestBody === null) {
        return request
    }
    return { ...request, requestBody: REDACTED_BODY }
}

// A test send holds whatever the person typed, such as a login code, under names the SDK's scrubbing doesn't know.
export const redactPushSendsInReplay = redactReplayRequests(redactPushSend)
