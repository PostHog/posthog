import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'

import { BroadcastPayload } from './navPanelAdShared'
import { pickNavPanelSlotCard } from './navPanelSlotCard'

const BROADCAST: BroadcastPayload = {
    broadcast: 'managed-warehouse-beta',
    text: 'Query everything in one place.',
    emoji: '🏠',
    emojiLabel: 'house emoji',
    title: 'Managed warehouse beta',
}

const CAMPAIGN = { id: 'campaign-1', product_key: 'session_replay' } as ProductPushCampaignApi

const NO_SUGGESTIONS_USER = { ...MOCK_DEFAULT_USER, allow_sidebar_suggestions: false }

describe('pickNavPanelSlotCard', () => {
    it.each([
        ['a broadcast over a running campaign', true, BROADCAST, CAMPAIGN, true, MOCK_DEFAULT_USER, 'broadcast'],
        ['the campaign when there is no broadcast', true, undefined, CAMPAIGN, true, MOCK_DEFAULT_USER, 'product_push'],
        ['the MCP card between campaigns', true, undefined, null, true, MOCK_DEFAULT_USER, 'mcp_connect'],
        ['nothing while the campaign request is in flight', true, undefined, null, false, MOCK_DEFAULT_USER, null],
        ['the MCP card when suggestions are off', true, undefined, CAMPAIGN, true, NO_SUGGESTIONS_USER, 'mcp_connect'],
        ['the MCP card for a malformed broadcast', true, { title: 'x' }, null, true, MOCK_DEFAULT_USER, 'mcp_connect'],
        ['nothing on hobby', false, BROADCAST, CAMPAIGN, true, MOCK_DEFAULT_USER, null],
        ['nothing before the user loads', true, undefined, null, true, null, null],
    ])('picks %s', (_, isCloudOrDev, broadcastPayload, activeCampaign, campaignResolved, user, expected) => {
        expect(
            pickNavPanelSlotCard({ isCloudOrDev, broadcastPayload, activeCampaign, campaignResolved, user })?.type ??
                null
        ).toBe(expected)
    })
})
