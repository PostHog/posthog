import posthog from 'posthog-js'

import { BroadcastPayload, NAV_PANEL_CARD_TYPE, NavPanelPlacement } from './navPanelAdShared'

// pinned: analytics event names in both maps. Renaming them breaks dashboards.
const BROADCAST_EVENTS = {
    shown: 'nav panel broadcast shown',
    dismissed: 'nav panel broadcast dismissed',
} as const

const MCP_CARD_EVENTS = {
    shown: 'nav panel mcp card shown',
    dismissed: 'nav panel mcp card dismissed',
    commandCopied: 'nav panel mcp card command copied',
} as const

export function captureBroadcastEvent(
    action: keyof typeof BROADCAST_EVENTS,
    broadcast: Pick<BroadcastPayload, 'broadcast' | 'productKey'>,
    placement: NavPanelPlacement
): void {
    posthog.capture(BROADCAST_EVENTS[action], {
        broadcast: broadcast.broadcast,
        card_type: NAV_PANEL_CARD_TYPE.BROADCAST,
        product_key: broadcast.productKey,
        placement,
    })
}

export function captureMcpCardEvent(action: keyof typeof MCP_CARD_EVENTS, placement: NavPanelPlacement): void {
    posthog.capture(MCP_CARD_EVENTS[action], { card_type: NAV_PANEL_CARD_TYPE.MCP_CONNECT, placement })
}
