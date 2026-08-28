import { CampaignPayload, isCampaignPayload } from './navPanelAdShared'

const VALID_PAYLOAD: CampaignPayload = {
    campaign: 'managed-warehouse-beta',
    text: 'Query everything in one place.',
    emoji: '🏠',
    emojiLabel: 'house emoji',
    title: 'Managed warehouse beta',
}

describe('navPanelAdShared', () => {
    describe('isCampaignPayload', () => {
        // Campaign payloads are hand-authored in the feature flag, so the guard has to keep
        // accepting every payload written before `productKey` existed.
        it.each([
            ['without productKey', VALID_PAYLOAD, true],
            ['with a productKey', { ...VALID_PAYLOAD, productKey: 'session_replay' }, true],
            ['with an explicitly undefined productKey', { ...VALID_PAYLOAD, productKey: undefined }, true],
            ['with a non-string productKey', { ...VALID_PAYLOAD, productKey: 42 }, false],
            ['missing a required field', { ...VALID_PAYLOAD, title: undefined }, false],
            ['not an object', 'managed-warehouse-beta', false],
        ])('accepts or rejects a payload %s', (_description, value, expected) => {
            expect(isCampaignPayload(value)).toBe(expected)
        })
    })
})
