/**
 * Body schemas for the Slack events trigger.
 *
 * We do NOT `safeParse` against these at runtime — Slack sends a long tail of
 * event types we deliberately accept-and-ignore (app_uninstalled, member_joined_channel,
 * etc.), so the handler is permissive. These schemas exist purely so the
 * agent-level `GET /schemas` can publish the two envelope shapes we actually
 * act on; they describe the contract for callers, not validate the wire.
 */

import { z } from 'zod'

/**
 * The two top-level Slack envelopes we route on. `event_callback.event` is
 * left as an open record because Slack's event subtypes are out-of-scope
 * here — refer to https://api.slack.com/events for the catalog.
 */
export const SlackEventBodySchema = z.discriminatedUnion('type', [
    z.object({
        type: z.literal('url_verification'),
        challenge: z.string(),
    }),
    z.object({
        type: z.literal('event_callback'),
        team_id: z.string().optional(),
        event: z.record(z.string(), z.unknown()),
    }),
])
