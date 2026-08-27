export type PosthogPropertyValue = string | number | boolean | null | undefined;

export type PosthogProperties = Record<string, PosthogPropertyValue>;

export const POSTHOG_PROJECT_ID_HEADER = "X-PostHog-Project-Id";

/**
 * Make a value safe to embed in an HTTP header value. Only printable ASCII
 * survives: latin1 is valid per RFC 9110 and undici accepts it, but Bun's
 * fetch — which the Claude Code CLI uses for `ANTHROPIC_CUSTOM_HEADERS` —
 * rejects any non-ASCII header value. NFKD plus the final strip is what
 * transliterates accented letters to their ASCII base (`più` → `piu`); the
 * combining-mark pass just keeps a stray mark from splitting a newline run
 * before it is collapsed to a single space.
 */
function sanitizeHeaderValue(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[\r\n]+/g, " ")
    .replace(/[^\x20-\x7e]/g, "");
}

function buildEntries(properties: PosthogProperties): Array<[string, string]> {
  const entries: Array<[string, string]> = [];
  for (const [key, value] of Object.entries(properties)) {
    if (value === null || value === undefined) continue;
    entries.push([
      `x-posthog-property-${key}`,
      sanitizeHeaderValue(String(value)),
    ]);
  }
  return entries;
}

/**
 * Build a `Record<string, string>` of `x-posthog-property-<name>` headers
 * suitable for `fetch()` init.headers. The LLM gateway lifts each header
 * onto the `$ai_generation` event it captures
 * (see `services/llm-gateway/src/llm_gateway/request_context.py` in
 * posthog/posthog). `null`/`undefined` values are dropped; values are
 * sanitized via {@link sanitizeHeaderValue}.
 */
export function buildPosthogPropertyHeaderRecord(
  properties: PosthogProperties,
): Record<string, string> {
  return Object.fromEntries(buildEntries(properties));
}

/**
 * Same property semantics as {@link buildPosthogPropertyHeaderRecord}, but
 * returns a newline-joined string of `key: value` lines — the format
 * `ANTHROPIC_CUSTOM_HEADERS` expects when wiring headers into the Claude
 * Agent SDK.
 */
export function buildPosthogPropertyHeaderLines(
  properties: PosthogProperties,
): string {
  return buildEntries(properties)
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
}

/**
 * Attribution node header for the person a request is spent on behalf of. The
 * gateway keys its per-user spend limit on this value, so it must be the same
 * node the spend-limit endpoint writes the limit against: the user's distinct
 * id, not their uuid (see products/ai_gateway/backend/logic.py, _spend_node).
 *
 * Trust model: for local sessions this header is asserted by the client, so
 * the limit it keys is a self-imposed guardrail, not a security boundary.
 * Cloud runs pin the node server-side into the run's scoped token.
 */
export const POSTHOG_USER_HEADER = "X-PostHog-User";

export function buildPosthogUserHeaderRecord(
  userNode: string | null | undefined,
): Record<string, string> {
  return userNode
    ? { [POSTHOG_USER_HEADER]: sanitizeHeaderValue(userNode) }
    : {};
}

export function buildPosthogUserHeaderLines(
  userNode: string | null | undefined,
): string {
  return userNode
    ? `${POSTHOG_USER_HEADER}: ${sanitizeHeaderValue(userNode)}`
    : "";
}

export function buildPosthogProjectHeaderRecord(
  projectId: number | null | undefined,
): Record<string, string> {
  return projectId ? { [POSTHOG_PROJECT_ID_HEADER]: String(projectId) } : {};
}

export function buildPosthogProjectHeaderLines(
  projectId: number | null | undefined,
): string {
  return projectId ? `${POSTHOG_PROJECT_ID_HEADER}: ${projectId}` : "";
}

export function buildPosthogScopedPropertyHeaderRecord(
  properties: PosthogProperties,
  projectId: number | null | undefined,
): Record<string, string> {
  return {
    ...buildPosthogPropertyHeaderRecord(properties),
    ...buildPosthogProjectHeaderRecord(projectId),
  };
}

export function buildPosthogScopedPropertyHeaderLines(
  properties: PosthogProperties,
  projectId: number | null | undefined,
): string {
  return [
    buildPosthogPropertyHeaderLines(properties),
    buildPosthogProjectHeaderLines(projectId),
  ]
    .filter(Boolean)
    .join("\n");
}

/** Header carrying the whole property set as one JSON object. */
export const POSTHOG_PROPERTIES_HEADER = "X-PostHog-Properties";

/**
 * Byte cap the Go gateway enforces on {@link POSTHOG_PROPERTIES_HEADER}; a
 * larger blob is rejected outright, losing every property including
 * `ai_product`. Keep in sync with `maxPropertiesLen` in the gateway's
 * `internal/httpapi/dispatch.go`.
 */
const MAX_PROPERTIES_BYTES = 8192;

const encoder = new TextEncoder();

function byteLength(value: string): number {
  return encoder.encode(value).length;
}

/**
 * Serialize properties for {@link POSTHOG_PROPERTIES_HEADER}, or `""` when
 * there is nothing to send.
 *
 * Keys beginning with `$` are dropped: the gateway strips reserved `$ai_*`
 * keys at the header boundary, so sending them silently loses them. Values
 * are sanitized like the per-property headers so a stray control character
 * cannot break the header block.
 *
 * Callers supply free-text values (task titles), so the blob can exceed
 * {@link MAX_PROPERTIES_BYTES}. Rather than let the gateway reject the whole
 * header, the longest string values are dropped one at a time until it fits,
 * preferring to lose descriptive text over attribution keys, which are short.
 */
export function buildPosthogPropertiesBlob(
  properties: PosthogProperties,
): string {
  const clean: PosthogProperties = {};
  for (const [key, value] of Object.entries(properties)) {
    if (value === null || value === undefined) continue;
    if (key.startsWith("$")) continue;
    // Keys are sanitized too: unlike the per-property headers, where the key
    // becomes the header name, here it is serialized into the header value,
    // so a non-ASCII key would make the whole request unsendable.
    const safeKey = sanitizeHeaderValue(key);
    if (!safeKey) continue;
    clean[safeKey] =
      typeof value === "string" ? sanitizeHeaderValue(value) : value;
  }
  if (Object.keys(clean).length === 0) return "";

  let blob = JSON.stringify(clean);
  while (byteLength(blob) > MAX_PROPERTIES_BYTES) {
    const longest = Object.entries(clean)
      .filter(([, value]) => typeof value === "string")
      .sort((a, b) => (b[1] as string).length - (a[1] as string).length)[0];
    // Only non-string values remain and they still overflow: send nothing
    // rather than a blob the gateway will reject.
    if (!longest) return "";
    delete clean[longest[0]];
    blob = JSON.stringify(clean);
  }
  return blob;
}

/**
 * {@link buildPosthogPropertiesBlob} as a `fetch()`-ready header record, empty
 * when there is nothing to send.
 */
export function buildPosthogPropertiesHeaderRecord(
  properties: PosthogProperties,
): Record<string, string> {
  const blob = buildPosthogPropertiesBlob(properties);
  return blob ? { [POSTHOG_PROPERTIES_HEADER]: blob } : {};
}

/**
 * {@link buildPosthogPropertiesBlob} as a single `key: value` line for
 * `ANTHROPIC_CUSTOM_HEADERS`, empty when there is nothing to send.
 */
export function buildPosthogPropertiesHeaderLines(
  properties: PosthogProperties,
): string {
  const blob = buildPosthogPropertiesBlob(properties);
  return blob ? `${POSTHOG_PROPERTIES_HEADER}: ${blob}` : "";
}
