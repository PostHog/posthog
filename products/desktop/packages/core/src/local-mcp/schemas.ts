import { z } from "zod";

/**
 * Payload contract for flags that offer an internal MCP server in the
 * marketplace (HOSTHOG_MCP_FLAG). The server config rides in the flag payload
 * instead of source so internal endpoints stay out of this public repo.
 */
export const flaggedMcpServerPayloadSchema = z.object({
  // ~/.claude.json server key; keys become MCP tool-name prefixes
  // (mcp__<name>__*), so keep them identifier-shaped like `claude mcp add`.
  name: z
    .string()
    .min(1)
    .max(100)
    .regex(/^[a-zA-Z0-9_-]+$/),
  url: z.url({ protocol: /^https?$/ }),
  /** Card title in the marketplace; falls back to `name`. */
  displayName: z.string().optional(),
  description: z.string().optional(),
  /** Brand domain for the card icon, resolved via the logo.dev proxy. */
  iconDomain: z.string().optional(),
});

export type FlaggedMcpServerPayload = z.infer<
  typeof flaggedMcpServerPayloadSchema
>;

/** Parses a flag payload, returning null when missing or malformed. */
export function parseFlaggedMcpServerPayload(
  payload: unknown,
): FlaggedMcpServerPayload | null {
  const result = flaggedMcpServerPayloadSchema.safeParse(payload);
  return result.success ? result.data : null;
}
