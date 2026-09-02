import { BroadcastPayload, isBroadcastPayload } from './navPanelAdShared'

const VALID_PAYLOAD: BroadcastPayload = {
    broadcast: 'managed-warehouse-beta',
    text: 'Query everything in one place.',
    emoji: '🏠',
    emojiLabel: 'house emoji',
    title: 'Managed warehouse beta',
}

describe('navPanelAdShared', () => {
    describe('isBroadcastPayload', () => {
        // Broadcast payloads are hand-authored in the feature flag, so the guard has to keep
        // accepting a payload that names no product.
        it.each([
            ['without productKey', VALID_PAYLOAD, true],
            ['with a productKey', { ...VALID_PAYLOAD, productKey: 'session_replay' }, true],
            ['with an explicitly undefined productKey', { ...VALID_PAYLOAD, productKey: undefined }, true],
            ['with a non-string productKey', { ...VALID_PAYLOAD, productKey: 42 }, false],
            ['missing a required field', { ...VALID_PAYLOAD, title: undefined }, false],
            ['not an object', 'managed-warehouse-beta', false],
        ])('accepts or rejects a payload %s', (_description, value, expected) => {
            expect(isBroadcastPayload(value)).toBe(expected)
        })
    })
})
