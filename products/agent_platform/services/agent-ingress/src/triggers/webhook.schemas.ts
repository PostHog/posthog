/**
 * Body schema for the webhook trigger.
 *
 * Webhook deliberately accepts arbitrary JSON — the agent's `agent.md` is the
 * contract for what payloads it understands at the *content* level. But we
 * still reject null / non-object bodies at the edge so the trigger can't
 * accidentally enqueue a `"null"`-string seed.
 */

import { z } from 'zod'

/** Minimum useful constraint: a JSON object. The shape inside is open. */
export const WebhookBodySchema = z.record(z.string(), z.unknown())
