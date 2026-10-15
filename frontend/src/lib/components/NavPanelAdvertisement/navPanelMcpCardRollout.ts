import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'

/** Whether the user is in the MCP card experiment at all, in either arm, without reporting an exposure. */
export function isInMcpCardRollout(): boolean {
    const variant = posthog.getFeatureFlag(FEATURE_FLAGS.NAV_PANEL_MCP_CARD, { send_event: false })
    return typeof variant === 'string'
}
