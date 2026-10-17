import { parseIncomingRequestLogMessage } from './hogFunctionSourceWebhookLastPayloadLogic'

describe('parseIncomingRequestLogMessage', () => {
    test.each([
        [
            'JSON body',
            'Incoming request:, {"event":"signup","distinct_id":"abc"}',
            '{\n  "event": "signup",\n  "distinct_id": "abc"\n}',
        ],
        ['non-JSON body', 'Incoming request:, plain text', 'plain text'],
        ['empty body', 'Incoming request:, ', ''],
    ])('%s', (_, message, expected) => {
        expect(parseIncomingRequestLogMessage(message)).toEqual(expected)
    })
})
